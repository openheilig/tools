import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.symbol.SourceType;
import java.io.*;
import java.util.*;
public class LabelGlobals extends GhidraScript {
  public void run() throws Exception {
    BufferedReader br = new BufferedReader(new FileReader(getScriptArgs()[0]));
    PrintWriter out = new PrintWriter("/tmp/gh/out.txt");
    br.readLine(); String line; Set<String> seen = new HashSet<>(); int n=0, skip=0;
    while ((line=br.readLine())!=null) {
      String[] f = line.split("\t"); if (f.length<2) continue;
      if (!seen.add(f[0])) continue;
      Address g = currentProgram.getAddressFactory().getAddress("0x"+f[1]);
      String nm = "bal_" + f[0].replaceAll("[^A-Za-z0-9_]", "_");
      try { createLabel(g, nm, true, SourceType.IMPORTED); n++; } catch (Exception e) { skip++; }
    }
    out.println("labelled="+n+" skipped="+skip); out.close(); br.close();
  }
}
