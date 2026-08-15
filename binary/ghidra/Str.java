import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import java.io.*;
public class Str extends GhidraScript {
  public void run() throws Exception {
    PrintWriter out = new PrintWriter(new FileWriter("/tmp/gh/out.txt"));
    for (String s : getScriptArgs()) {
      Address a = currentProgram.getAddressFactory().getAddress(s);
      StringBuilder sb = new StringBuilder();
      for (int i=0;i<120;i++){ byte b = getByte(a.add(i)); if (b==0) break; sb.append((char)(b&0xff)); }
      out.println(s + " = \"" + sb + "\"");
    }
    out.close();
  }
}
