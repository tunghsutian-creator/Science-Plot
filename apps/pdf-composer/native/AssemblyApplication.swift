import AppKit
import WebKit

@MainActor
final class AssemblyApplication: NSObject, NSApplicationDelegate, NSWindowDelegate, WKNavigationDelegate {
    private(set) var window: NSWindow!
    private(set) var webView: WKWebView!
    private let bridge: NativeBridge
    private let bundledWebRoot: URL?
    private var resourceRoot: URL!
    private var ready = false
    private var dirty = false
    private var pendingMenus: [String] = []
    private var closeAfterSave = false
    private var quitAfterSave = false
    private var allowingClose = false

    init(bundledWebRoot: URL? = nil, bridge: NativeBridge = NativeBridge()) {
        self.bundledWebRoot = bundledWebRoot; self.bridge = bridge
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        resourceRoot = bundledWebRoot ?? Bundle.main.resourceURL!.appendingPathComponent("web", isDirectory: true)
        let index = resourceRoot.appendingPathComponent("index.html")
        guard FileManager.default.fileExists(atPath: index.path) else {
            let alert = NSAlert(); alert.messageText = "Figure Assembly is incomplete"
            alert.informativeText = "The bundled web interface is missing. Rebuild the app with its local assets."
            alert.runModal(); NSApp.terminate(nil); return
        }
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        configuration.userContentController.add(bridge, name: "assembly")
        webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = self
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1420, height: 940),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.minSize = NSSize(width: 1000, height: 700)
        window.title = "Figure Assembly"; window.contentView = webView
        window.delegate = self; window.isReleasedWhenClosed = false
        bridge.webView = webView; bridge.window = window
        bridge.documentState = { [weak self] title, dirty in self?.setDocumentState(title: title, dirty: dirty) }
        bridge.saveFinished = { [weak self] success in
            if !success { self?.closeAfterSave = false; self?.quitAfterSave = false }
        }
        NSApp.mainMenu = makeMenus()
        window.center(); window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        Task { @MainActor in
            do {
                let rules = """
                [{"trigger":{"url-filter":"^(https?|wss?|ftp)://"},"action":{"type":"block"}}]
                """
                let list = try await WKContentRuleListStore.default().compileContentRuleList(
                    forIdentifier: "FigureAssemblyOffline", encodedContentRuleList: rules)
                if let list { configuration.userContentController.add(list) }
                webView.loadFileURL(index, allowingReadAccessTo: resourceRoot)
            } catch {
                let alert = NSAlert(); alert.messageText = "The offline interface could not open"
                alert.informativeText = error.localizedDescription; _ = await alert.beginSheetModal(for: window)
            }
        }
    }

    private func setDocumentState(title: String, dirty: Bool) {
        self.dirty = dirty
        window.title = (title.isEmpty ? "Untitled" : title) + " — Figure Assembly"
        window.isDocumentEdited = dirty
        if !ready { ready = true; pendingMenus.forEach(dispatchMenu); pendingMenus.removeAll() }
        if !dirty && (closeAfterSave || quitAfterSave) {
            let quit = quitAfterSave
            allowingClose = true; closeAfterSave = false; quitAfterSave = false
            if quit { NSApp.terminate(nil) } else { window.close() }
        }
    }

    @objc func menuAction(_ sender: NSMenuItem) {
        guard let action = sender.representedObject as? String else { return }
        if ready { dispatchMenu(action) } else { pendingMenus.append(action) }
    }

    private func dispatchMenu(_ action: String) {
        guard let data = try? JSONSerialization.data(withJSONObject: action, options: [.fragmentsAllowed]),
              let json = String(data: data, encoding: .utf8) else { return }
        webView.evaluateJavaScript("window.dispatchEvent(new CustomEvent('assembly-menu',{detail:\(json)}))", completionHandler: nil)
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        if allowingClose || !dirty { return true }
        confirmDiscard(quitting: false)
        return false
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if allowingClose || !dirty { return .terminateNow }
        confirmDiscard(quitting: true)
        return .terminateCancel
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    @objc private func showAbout(_ sender: Any?) {
        let credits = "GNU General Public License v2\nSource: https://github.com/tunghsutian-creator/Science-Plot\nBundled dependency and font licenses are available in File → Licenses."
        NSApp.orderFrontStandardAboutPanel(options: [.credits: NSAttributedString(string: credits)])
    }

    @objc private func showLicenses(_ sender: Any?) {
        let notices = resourceRoot.appendingPathComponent("THIRD_PARTY_NOTICES.txt")
        if FileManager.default.fileExists(atPath: notices.path) { NSWorkspace.shared.open(notices) }
    }

    private func confirmDiscard(quitting: Bool) {
        guard window.attachedSheet == nil else { return }
        closeAfterSave = false; quitAfterSave = false
        let alert = NSAlert()
        alert.messageText = "Save changes before \(quitting ? "quitting" : "closing")?"
        alert.informativeText = "Your current layout has unsaved changes."
        alert.addButton(withTitle: "Save"); alert.addButton(withTitle: "Discard Changes"); alert.addButton(withTitle: "Cancel")
        alert.beginSheetModal(for: window) { [weak self] response in
            guard let self else { return }
            if response == .alertFirstButtonReturn {
                self.closeAfterSave = !quitting; self.quitAfterSave = quitting; self.dispatchMenu("save")
            } else if response == .alertSecondButtonReturn {
                self.allowingClose = true
                if quitting { NSApp.terminate(nil) } else { self.window.close() }
            }
        }
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction) async -> WKNavigationActionPolicy {
        guard navigationAction.targetFrame?.isMainFrame == true,
              let url = navigationAction.request.url, url.isFileURL,
              url.standardizedFileURL == resourceRoot.appendingPathComponent("index.html").standardizedFileURL else {
            return .cancel
        }
        return .allow
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        if (error as NSError).code != NSURLErrorCancelled {
            let alert = NSAlert(); alert.messageText = "The local interface could not open"
            alert.informativeText = error.localizedDescription; alert.beginSheetModal(for: window)
        }
    }

    private func makeMenus() -> NSMenu {
        let menu = NSMenu()
        let app = NSMenu(); let appItem = NSMenuItem(); appItem.submenu = app; menu.addItem(appItem)
        let about = app.addItem(withTitle: "About Figure Assembly", action: #selector(showAbout(_:)), keyEquivalent: "")
        about.target = self
        app.addItem(.separator())
        app.addItem(withTitle: "Quit Figure Assembly", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        let file = NSMenu(title: "File"); let fileItem = NSMenuItem(); fileItem.submenu = file; menu.addItem(fileItem)
        add(file, "New Layout", "new", "n"); add(file, "Open Layout…", "open", "o")
        add(file, "Import Figures…", "import", "i"); file.addItem(.separator())
        add(file, "Save", "save", "s"); add(file, "Save As…", "saveAs", "s", shift: true)
        add(file, "Export…", "export", "e"); file.addItem(.separator())
        file.addItem(withTitle: "Close", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
        let licenses = file.addItem(withTitle: "Licenses", action: #selector(showLicenses(_:)), keyEquivalent: "")
        licenses.target = self
        let edit = NSMenu(title: "Edit"); let editItem = NSMenuItem(); editItem.submenu = edit; menu.addItem(editItem)
        add(edit, "Undo", "undo", "z"); add(edit, "Redo", "redo", "z", shift: true)
        edit.addItem(.separator())
        edit.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        return menu
    }

    private func add(_ menu: NSMenu, _ title: String, _ action: String, _ key: String, shift: Bool = false) {
        let item = NSMenuItem(title: title, action: #selector(menuAction(_:)), keyEquivalent: key)
        item.target = self; item.representedObject = action
        item.keyEquivalentModifierMask = shift ? [.command, .shift] : [.command]
        menu.addItem(item)
    }
}
