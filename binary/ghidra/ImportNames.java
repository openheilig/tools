import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.SourceType;
import java.io.*;
public class ImportNames extends GhidraScript {
  public void run() throws Exception {
    PrintWriter out = new PrintWriter("/tmp/gh/out.txt");
    BufferedReader br = new BufferedReader(new FileReader(getScriptArgs()[0]));
    String line = br.readLine(); // header
    int applied=0, skipExisting=0, noFunc=0, created=0, err=0;
    while ((line = br.readLine()) != null) {
      String[] p = line.split("\t");
      if (p.length < 3) continue;
      Address a = currentProgram.getAddressFactory().getAddress(p[0]);
      Function f = getFunctionAt(a);
      if (f == null) {
        f = getFunctionContaining(a);
        if (f != null && !f.getEntryPoint().equals(a)) { noFunc++; continue; }
        if (f == null) { try { f = createFunction(a, null); created++; } catch (Exception e) { noFunc++; continue; } }
        if (f == null) { noFunc++; continue; }
      }
      String n = f.getName();
      if (!n.startsWith("FUN_") && !n.startsWith("thunk_FUN_")) { skipExisting++; continue; }
      try { f.setName(p[1], SourceType.IMPORTED); f.setComment("RTTI vtable: " + p[2] + " slot " + p[3]); applied++; }
      catch (Exception e) { err++; }
    }
    br.close();
    out.println("applied="+applied+" skipExisting="+skipExisting+" noFuncEntry="+noFunc+" created="+created+" err="+err);
    out.close();
  }
}
