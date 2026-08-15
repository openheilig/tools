import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import java.io.*;
public class Dis extends GhidraScript {
  public void run() throws Exception {
    PrintWriter out = new PrintWriter(new FileWriter("/tmp/gh/out.txt"));
    String[] a = getScriptArgs();
    Address start = currentProgram.getAddressFactory().getAddress(a[0]);
    int n = Integer.parseInt(a[1]);
    Listing l = currentProgram.getListing();
    InstructionIterator it = l.getInstructions(start, true);
    int i=0;
    while (it.hasNext() && i++ < n) {
      Instruction ins = it.next();
      StringBuilder sb = new StringBuilder();
      sb.append(ins.getAddress()).append("  ").append(ins.toString());
      // append referenced data / strings
      for (Reference r : ins.getReferencesFrom()) {
        Address t = r.getToAddress();
        Data dd = l.getDataAt(t);
        if (dd != null && dd.hasStringValue()) sb.append("   ; \"").append(dd.getValue()).append("\"");
        else { Symbol s = getSymbolAt(t); if (s != null && !s.getName().startsWith("LAB_") && !s.getName().startsWith("DAT_")) sb.append("   ; ").append(s.getName()); }
      }
      out.println(sb);
    }
    out.close();
  }
}
