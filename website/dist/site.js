const tabList = document.querySelector("[data-preview-tabs]");
const screenshots = Array.from(document.querySelectorAll("[data-preview]"));

function selectScreenshot(index, moveFocus = false) {
  screenshots.forEach((panel, position) => {
    const active = position === index;
    const button = tabList.children[position];
    button.setAttribute("aria-selected", String(active));
    button.tabIndex = active ? 0 : -1;
    panel.hidden = !active;
    if (active && moveFocus) button.focus();
  });
}

for (const [index, panel] of screenshots.entries()) {
  const name = panel.dataset.preview;
  const button = document.createElement("button");
  button.type = "button";
  button.id = `tab-${name}`;
  button.textContent = name[0].toUpperCase() + name.slice(1);
  button.setAttribute("role", "tab");
  button.setAttribute("aria-controls", `screen-${name}`);
  button.addEventListener("click", () => selectScreenshot(index));
  tabList.append(button);
  panel.id = `screen-${name}`;
  panel.setAttribute("role", "tabpanel");
  panel.setAttribute("aria-labelledby", button.id);
}

tabList.setAttribute("role", "tablist");
tabList.addEventListener("keydown", event => {
  const from = Array.from(tabList.children).indexOf(event.target);
  const last = screenshots.length - 1;
  const destination = {
    ArrowLeft: from === 0 ? last : from - 1,
    ArrowRight: from === last ? 0 : from + 1,
    Home: 0,
    End: last,
  }[event.key];
  if (from < 0 || destination === undefined) return;
  event.preventDefault();
  selectScreenshot(destination, true);
});

selectScreenshot(0);
tabList.hidden = false;

const copy = document.querySelector("#copy-example");
const status = document.querySelector("#copy-status");
let copyReset;
if (navigator.clipboard?.writeText) {
  copy.hidden = false;
  copy.addEventListener("click", async () => {
    clearTimeout(copyReset);
    try {
      await navigator.clipboard.writeText(document.querySelector("#api-example").textContent);
      status.textContent = "PowerShell example copied.";
      copy.textContent = "Copied";
    } catch {
      status.textContent = "Clipboard unavailable. You can select and copy the example.";
      copy.textContent = "Unavailable";
    }
    copyReset = setTimeout(() => { copy.textContent = "Copy"; }, 2200);
  });
}

async function localDownload(filename) {
  const path = "downloads/" + filename;
  try {
    const file = await fetch(path, { method: "HEAD" });
    if (file.ok && !file.headers.get("content-type")?.startsWith("text/html")) return path;
  } catch {
    // Static deployment can omit the local preview binaries.
  }
  return null;
}

async function selectLocalInstaller() {
  if (!["localhost", "127.0.0.1", "[::1]"].includes(location.hostname)) return;
  const name = "OctaDeck-Setup-x64.exe";
  const path = await localDownload(name);
  if (!path) return;
  const installer = document.querySelector("#installer");
  installer.href = path;
  installer.download = name;
  document.querySelector("#installer-note").textContent = "Local preview build. This installer is unsigned.";
}

selectLocalInstaller();
