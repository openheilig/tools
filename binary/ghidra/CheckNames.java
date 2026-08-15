import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import java.io.*;
public class CheckNames extends GhidraScript {
  public void run() throws Exception {
    PrintWriter out = new PrintWriter("/tmp/gh/out.txt");
    BufferedReader br = new BufferedReader(new FileReader(getScriptArgs()[0]));
    br.readLine();
    int total=0, entry=0, inside=0, none=0; String line;
    while ((line=br.readLine())!=null) {
      String[] p=line.split("\t"); if (p.length<3) continue; total++;
      Address a=currentProgram.getAddressFactory().getAddress(p[0]);
      if (getFunctionAt(a)!=null) entry++;
      else if (getFunctionContaining(a)!=null) inside++;
      else none++;
    }
    br.close();
    out.println("total="+total+" exactEntry="+entry+" midFunction="+inside+" noCode="+none);
    out.close();
  }
}
