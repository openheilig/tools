import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import java.io.*;
public class Tbl extends GhidraScript {
  public void run() throws Exception {
    PrintWriter out = new PrintWriter(new FileWriter("/tmp/gh/out.txt"));
    String[] a = getScriptArgs();
    Address base = currentProgram.getAddressFactory().getAddress(a[0]);
    int n = Integer.parseInt(a[1]);
    for (int i=0;i<n;i++){
      long v = getInt(base.add(i*4L)) & 0xffffffffL;
      out.printf("%3d 0x%02x -> 0x%08x%n", i, i, v);
    }
    out.close();
  }
}
