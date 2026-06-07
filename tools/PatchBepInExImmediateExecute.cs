using Mono.Cecil;
using Mono.Cecil.Cil;

if (args.Length != 1)
{
    Console.Error.WriteLine("usage: PatchBepInExImmediateExecute <BepInEx.Unity.IL2CPP.dll>");
    return 2;
}

var assemblyPath = args[0];

var asm = AssemblyDefinition.ReadAssembly(
    assemblyPath,
    new ReaderParameters { ReadSymbols = false, ReadingMode = ReadingMode.Immediate });
var module = asm.MainModule;
var chainloader = module.GetType("BepInEx.Unity.IL2CPP.IL2CPPChainloader")
    ?? throw new InvalidOperationException("IL2CPPChainloader type not found");

var initialize = chainloader.Methods.First(m => m.Name == "Initialize");
var onInvoke = chainloader.Methods.First(m => m.Name == "OnInvokeMethod");

if (initialize.Body.Instructions.Any(ins =>
    ins.OpCode == OpCodes.Ldstr
    && ins.Operand is string existing
    && existing == "IL2CPP chainloader executed immediately after runtime invoke patch"))
{
    Console.WriteLine("already patched: immediate chainloader execution marker is present");
    return 0;
}

MethodReference FindCallOperand(MethodDefinition method, string declaringTypeContains, string methodName)
{
    foreach (var ins in method.Body.Instructions)
    {
        if ((ins.OpCode == OpCodes.Call || ins.OpCode == OpCodes.Callvirt)
            && ins.Operand is MethodReference mr
            && mr.Name == methodName
            && mr.DeclaringType.FullName.Contains(declaringTypeContains, StringComparison.Ordinal))
        {
            return mr;
        }
    }
    throw new InvalidOperationException($"call not found: {declaringTypeContains}.{methodName}");
}

var preloadInterop = FindCallOperand(onInvoke, "Il2CppInteropManager", "PreloadInteropAssemblies");
var getInstance = FindCallOperand(onInvoke, "IL2CPPChainloader", "get_Instance");
var execute = FindCallOperand(onInvoke, "BaseChainloader", "Execute");
var getRuntimeDetour = FindCallOperand(onInvoke, "IL2CPPChainloader", "get_RuntimeInvokeDetour");
var dispose = FindCallOperand(onInvoke, "System.IDisposable", "Dispose");

var runtimeInvokePatchedLdstr = initialize.Body.Instructions.FirstOrDefault(ins =>
    ins.OpCode == OpCodes.Ldstr
    && ins.Operand is string value
    && value == "Runtime invoke patched")
    ?? throw new InvalidOperationException("Runtime invoke patched log string not found");

var logCall = runtimeInvokePatchedLdstr.Next;
while (logCall is not null && logCall.OpCode != OpCodes.Callvirt)
{
    logCall = logCall.Next;
}

if (logCall is null)
{
    throw new InvalidOperationException("Runtime invoke patched log call not found");
}

var ret = logCall.Next;
if (ret is null || ret.OpCode != OpCodes.Ret)
{
    throw new InvalidOperationException("expected ret after Runtime invoke patched log call");
}

var getLog = initialize.Body.Instructions
    .Where(ins => ins.OpCode == OpCodes.Call && ins.Operand is MethodReference mr && mr.Name == "get_Log")
    .Select(ins => (MethodReference)ins.Operand)
    .First();
var logMethod = (MethodReference)logCall.Operand;

var il = initialize.Body.GetILProcessor();
var injected = new[]
{
    il.Create(OpCodes.Call, preloadInterop),
    il.Create(OpCodes.Call, getInstance),
    il.Create(OpCodes.Callvirt, execute),
    il.Create(OpCodes.Call, getRuntimeDetour),
    il.Create(OpCodes.Callvirt, dispose),
    il.Create(OpCodes.Call, getLog),
    il.Create(OpCodes.Ldc_I4_S, (sbyte)0x20),
    il.Create(OpCodes.Ldstr, "IL2CPP chainloader executed immediately after runtime invoke patch"),
    il.Create(OpCodes.Callvirt, logMethod),
};

foreach (var ins in injected)
{
    il.InsertBefore(ret, ins);
}

var tempPath = assemblyPath + ".patched-tmp";
var backupPath = assemblyPath + ".bak-disco-immediate-execute-" + DateTime.Now.ToString("yyyyMMddHHmmss");
File.Copy(assemblyPath, backupPath, overwrite: false);
Console.WriteLine($"backup: {backupPath}");
asm.Write(tempPath);
File.Move(tempPath, assemblyPath, overwrite: true);
Console.WriteLine("patched: executes IL2CPP chainloader immediately after runtime invoke patch");
return 0;
