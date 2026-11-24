using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Net;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

internal sealed class RelayWindow : Form
{
    private const string Address = "http://127.0.0.1:8520/";
    private readonly string home;
    private readonly string source;
    private readonly WebView2 view = new WebView2();
    private Process server;

    private RelayWindow(string source, string home)
    {
        this.source = source;
        this.home = home;
        Text = "MuxDeck";
        Icon = System.Drawing.Icon.ExtractAssociatedIcon(Application.ExecutablePath);
        Width = 1180;
        Height = 800;
        MinimumSize = new Size(420, 480);
        StartPosition = FormStartPosition.CenterScreen;
        BackColor = Color.FromArgb(17, 18, 17);
        view.DefaultBackgroundColor = BackColor;
        view.Dock = DockStyle.Fill;
        Controls.Add(view);
        Shown += async (sender, args) =>
        {
            try { await OpenDashboard(); }
            catch (Exception error)
            {
                MessageBox.Show(error.Message, "MuxDeck", MessageBoxButtons.OK, MessageBoxIcon.Error);
                Close();
            }
        };
    }

    private static bool Ready()
    {
        try
        {
            var request = (HttpWebRequest)WebRequest.Create(Address + "health");
            request.Timeout = 500;
            request.Proxy = null;
            request.AllowAutoRedirect = false;
            using (var response = request.GetResponse())
                return response.Headers["X-Model-Relay"] == "1";
        }
        catch (WebException) { return false; }
    }

    private async Task OpenDashboard()
    {
        if (!await Task.Run((Func<bool>)Ready))
        {
            var embedded = Path.GetFullPath(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, @"..\runtime\python.exe"));
            var python = File.Exists(embedded) ? embedded : Path.Combine(home, @".venv\Scripts\python.exe");
            var command = new ProcessStartInfo(python,
                "-m uvicorn app:app --host 127.0.0.1 --port 8520 --no-access-log");
            command.WorkingDirectory = source;
            command.UseShellExecute = false;
            command.CreateNoWindow = true;
            command.EnvironmentVariables["MUXDECK_HOME"] = Path.Combine(home, "data");
            command.EnvironmentVariables["TEMP"] = Directory.CreateDirectory(Path.Combine(home, "temp")).FullName;
            command.EnvironmentVariables["TMP"] = command.EnvironmentVariables["TEMP"];
            command.EnvironmentVariables["PYTHONDONTWRITEBYTECODE"] = "1";
            server = Process.Start(command);
            for (int i = 0; i < 30; ++i)
            {
                if (await Task.Run((Func<bool>)Ready)) break;
                if (server.HasExited) throw new InvalidOperationException("MuxDeck could not start on port 8520.");
                await Task.Delay(250);
            }
            if (!await Task.Run((Func<bool>)Ready)) throw new InvalidOperationException("MuxDeck did not start.");
        }

        var environment = await CoreWebView2Environment.CreateAsync(null, Path.Combine(home, "webview"));
        await view.EnsureCoreWebView2Async(environment);
        view.CoreWebView2.Settings.AreDevToolsEnabled = false;
        view.CoreWebView2.Settings.AreDefaultContextMenusEnabled = false;
        view.CoreWebView2.Profile.DefaultDownloadFolderPath = Directory.CreateDirectory(Path.Combine(home, "downloads")).FullName;
        view.CoreWebView2.NavigationStarting += (sender, args) =>
        {
            if (!args.Uri.StartsWith(Address, StringComparison.Ordinal)) args.Cancel = true;
        };
        view.CoreWebView2.NewWindowRequested += (sender, args) =>
        {
            args.Handled = true;
            Uri target;
            if (args.IsUserInitiated && Uri.TryCreate(args.Uri, UriKind.Absolute, out target)
                && (target.Scheme == Uri.UriSchemeHttps || target.Scheme == Uri.UriSchemeHttp))
                Process.Start(new ProcessStartInfo(target.AbsoluteUri) { UseShellExecute = true });
        };
        view.Source = new Uri(Address);
    }

    protected override void OnFormClosed(FormClosedEventArgs args)
    {
        view.Dispose();
        if (server != null)
        {
            if (!server.HasExited)
            {
                var stop = new ProcessStartInfo("taskkill.exe", "/T /F /PID " + server.Id);
                stop.UseShellExecute = false;
                stop.CreateNoWindow = true;
                using (var process = Process.Start(stop)) process.WaitForExit(2500);
            }
            server.Dispose();
        }
        base.OnFormClosed(args);
    }

    [STAThread]
    private static void Main(string[] args)
    {
        if (args.Length < 1 || args.Length > 2 || !File.Exists(Path.Combine(args[0], "app.py")))
        {
            MessageBox.Show("Launch MuxDeck using the installed shortcut.", "MuxDeck");
            return;
        }
        var home = args.Length == 2 ? args[1] :
            Directory.GetParent(AppDomain.CurrentDomain.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar)).FullName;
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        Application.Run(new RelayWindow(args[0], home));
    }
}
