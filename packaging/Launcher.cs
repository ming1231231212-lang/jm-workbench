using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

class Launcher {
    [STAThread]
    static void Main(string[] args) {
        try {
            string root = AppDomain.CurrentDomain.BaseDirectory;
            string python = Path.Combine(root, "runtime", "pythonw.exe");
            if (!File.Exists(python)) throw new Exception("请先完整解压 ZIP，再打开 JM工作台.exe。不要单独移动 EXE 文件。");
            string name = Path.GetFileNameWithoutExtension(Application.ExecutablePath);
            string command = name.Contains("退出") ? "stop" : name.Contains("检查") ? "diagnostics" : "start";
            ProcessStartInfo info = new ProcessStartInfo(python, "-B -m jm_workbench.portable " + command);
            info.WorkingDirectory = root;
            info.UseShellExecute = false;
            info.CreateNoWindow = true;
            info.WindowStyle = ProcessWindowStyle.Hidden;
            Process.Start(info);
        } catch (Exception error) {
            MessageBox.Show(error.Message, "JM工作台", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}
