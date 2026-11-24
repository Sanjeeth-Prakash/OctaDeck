using System;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Security.Cryptography;
using System.Windows.Forms;

internal static class Setup
{
    [STAThread]
    private static int Main(string[] args)
    {
        bool installOnly = args.Length == 3 && args[0] == "--install-only" && args[1] == "--root";
        if (args.Length != 0 && !installOnly) return 2;
        Application.EnableVisualStyles();
        try
        {
            var home = installOnly ? Path.GetFullPath(args[2]) : ChooseFolder();
            if (home == null) return 0;
            var bundle = Install(home);
            var desktop = Path.Combine(bundle,"desktop");
            var launcher = Path.Combine(desktop,"MuxDeck.exe");
            var arguments = "\"" + Path.Combine(bundle,"app") + "\" \"" + home + "\"";
            dynamic shell = Activator.CreateInstance(Type.GetTypeFromProgID("WScript.Shell"));
            dynamic shortcut = shell.CreateShortcut(Path.Combine(home,"MuxDeck.lnk"));
            shortcut.TargetPath = launcher;
            shortcut.Arguments = arguments;
            shortcut.WorkingDirectory = desktop;
            shortcut.IconLocation = launcher + ",0";
            shortcut.Description = "Open MuxDeck";
            shortcut.Save();
            if (!installOnly)
                Process.Start(new ProcessStartInfo(launcher, arguments) {
                    WorkingDirectory = desktop, UseShellExecute = false
                });
            return 0;
        }
        catch (Exception error)
        {
            if (installOnly) Console.Error.WriteLine(error.Message);
            else MessageBox.Show(error.Message, "MuxDeck Setup", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }

    private static string ChooseFolder()
    {
        using (var dialog = new FolderBrowserDialog())
        {
            dialog.Description = "Choose where MuxDeck should store the app, data, and browser profile.";
            dialog.SelectedPath = AppDomain.CurrentDomain.BaseDirectory;
            if (dialog.ShowDialog() != DialogResult.OK) return null;
            var selected = dialog.SelectedPath;
            if (File.Exists(Path.Combine(selected, "Model Relay.lnk")) ||
                File.Exists(Path.Combine(selected, "MuxDeck.lnk")))
                return selected;
            return Path.Combine(selected, "MuxDeck");
        }
    }

    private static string Install(string home)
    {
        using (var payload = Assembly.GetExecutingAssembly().GetManifestResourceStream("payload.zip"))
        {
            if (payload == null) throw new IOException("Application package is missing.");
            byte[] digest;
            using (var sha = SHA256.Create()) digest = sha.ComputeHash(payload);
            var version = BitConverter.ToString(digest).Replace("-", "").Substring(0, 16).ToLowerInvariant();
            var installPath = Path.Combine(home, "app-" + version);
            if (!Directory.Exists(installPath))
            {
                Directory.CreateDirectory(home);
                var staged = Path.Combine(home, ".setup-" + Guid.NewGuid().ToString("N"));
                try
                {
                    Directory.CreateDirectory(staged);
                    payload.Position = 0;
                    using (var archive = new ZipArchive(payload, ZipArchiveMode.Read))
                        foreach (var entry in archive.Entries)
                        {
                            var target = Path.GetFullPath(Path.Combine(staged, entry.FullName));
                            if (!target.StartsWith(staged + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
                                throw new IOException("Unexpected file path in application package.");
                            Directory.CreateDirectory(Path.GetDirectoryName(target));
                            entry.ExtractToFile(target, false);
                        }
                    try { Directory.Move(staged, installPath); }
                    catch (IOException) { if (!Directory.Exists(installPath)) throw; }
                }
                finally { if (Directory.Exists(staged)) Directory.Delete(staged, true); }
            }
            if (!File.Exists(Path.Combine(installPath, "desktop", "MuxDeck.exe")))
                throw new IOException("The app installation is incomplete.");
            return installPath;
        }
    }
}
