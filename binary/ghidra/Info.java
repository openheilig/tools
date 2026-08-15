import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import java.io.*;
public class Info extends GhidraScript {
  public void run() throws Exception {
    PrintWriter out = new PrintWriter(new FileWriter("/tmp/gh/out.txt"));
    for (String s : getScriptArgs()) {
      Address a = currentProgram.getAddressFactory().getAddress(s);
      Function f = getFunctionContaining(a);
      out.println("ADDR " + s + " block=" + currentProgram.getMemory().getBlock(a)
        + " func=" + (f==null?"none":f.getName()+"@"+f.getEntryPoint()));
      ReferenceIterator ri = currentProgram.getReferenceManager().getReferencesTo(a);
      int c=0;
      while (ri.hasNext() && c++<12) { Reference r = ri.next();
        Function g = getFunctionContaining(r.getFromAddress());
        out.println("   <- " + r.getFromAddress() + " " + r.getReferenceType() + " in " + (g==null?"?":g.getName())); }
      if (c==0) out.println("   <- (no refs)");
    }
    out.close();
  }
}
