import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import java.io.*;
import java.util.*;
public class Consumers extends GhidraScript {
  public void run() throws Exception {
    String[] a = getScriptArgs();
    BufferedReader br = new BufferedReader(new FileReader(a[0]));
    PrintWriter out = new PrintWriter(new FileWriter(a[1]));
    Function parser = getFunctionContaining(currentProgram.getAddressFactory().getAddress(a[2]));
    out.println("key\tglobal\tnconsumers\tconsumers");
    br.readLine(); String line; Set<String> done = new HashSet<>();
    Map<String,Set<String>> byFunc = new TreeMap<>();
    while ((line=br.readLine())!=null) {
      String[] f = line.split("\t"); if (f.length<2) continue;
      if (!done.add(f[0])) continue;
      Address g = currentProgram.getAddressFactory().getAddress("0x"+f[1]);
      TreeSet<String> cons = new TreeSet<>();
      for (Reference r : getReferencesTo(g)) {
        Function fn = getFunctionContaining(r.getFromAddress());
        if (fn == null) continue;
        if (parser != null && fn.equals(parser)) continue;
        cons.add(fn.getName()+"@"+fn.getEntryPoint());
        byFunc.computeIfAbsent(fn.getName()+"@"+fn.getEntryPoint(), k->new TreeSet<>()).add(f[0]);
      }
      out.println(f[0]+"\t"+f[1]+"\t"+cons.size()+"\t"+String.join(" ", cons));
    }
    out.println();
    out.println("=== by consumer function ===");
    List<Map.Entry<String,Set<String>>> es = new ArrayList<>(byFunc.entrySet());
    es.sort((x,y)->y.getValue().size()-x.getValue().size());
    for (Map.Entry<String,Set<String>> e : es)
      out.println(e.getKey()+"\t"+e.getValue().size()+"\t"+String.join(" ", e.getValue()));
    br.close(); out.close();
  }
}
