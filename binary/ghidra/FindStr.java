import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import java.io.*;
public class FindStr extends GhidraScript {
  public void run() throws Exception {
    PrintWriter out = new PrintWriter(new FileWriter("/tmp/gh/out.txt"));
    String needle = getScriptArgs()[0].toLowerCase();
    DataIterator it = currentProgram.getListing().getDefinedData(true);
    int hits=0;
    while (it.hasNext() && hits < 60) {
      Data d = it.next();
      if (!d.hasStringValue()) continue;
      String v = d.getValue().toString();
      if (!v.toLowerCase().contains(needle)) continue;
      hits++;
      out.println("STR " + d.getAddress() + "  \"" + v.replace("\n","\\n") + "\"");
      for (Reference r : getReferencesTo(d.getAddress())) {
        Function f = getFunctionContaining(r.getFromAddress());
        out.println("   <- " + r.getFromAddress() + "  " + (f==null?"?":f.getName()+"@"+f.getEntryPoint()));
      }
    }
    out.println("hits=" + hits);
    out.close();
  }
}
