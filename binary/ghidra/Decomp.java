import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
public class Decomp extends GhidraScript {
  java.io.PrintWriter out;
  public void run() throws Exception {
    out = new java.io.PrintWriter("/tmp/gh/out.txt");
    String[] args = getScriptArgs();
    DecompInterface d = new DecompInterface();
    DecompileOptions o = new DecompileOptions();
    o.setMaxPayloadMBytes(96);
    d.setOptions(o);
    d.openProgram(currentProgram);
    for (String a : args) {
      Address ad = currentProgram.getAddressFactory().getAddress(a);
      Function f = getFunctionContaining(ad);
      if (f == null) { out.println("=== " + a + " NO_FUNCTION"); continue; }
      DecompileResults r = d.decompileFunction(f, 120, monitor);
      out.println("=== " + a + " " + f.getName() + " @" + f.getEntryPoint());
      if (r.decompileCompleted()) out.println(r.getDecompiledFunction().getC());
      else out.println("DECOMP_FAILED: " + r.getErrorMessage());
    }
    d.dispose(); out.close();
  }
}
