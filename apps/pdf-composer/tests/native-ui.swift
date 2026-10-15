import AppKit
import Foundation
import UniformTypeIdentifiers
import WebKit

@MainActor
final class UITestDialogs: NativeDialogs {
    weak var window: NSWindow?
    var imports: [URL] = []
    var opening: URL?
    var saving: URL?
    func importFiles() async throws -> [URL] { imports }
    func openProject() async throws -> URL? { opening }
    func saveFile(name: String, type: UTType) async throws -> URL? { saving }
}

enum UITestError: Error { case failed(String) }

@MainActor
final class NativeUIRun {
    let app: AssemblyApplication
    let bridge: NativeBridge
    let dialogs: UITestDialogs
    let output: URL
    var assertions: [String] = []
    private var heldCleanState: (() -> Void)?
    init(app: AssemblyApplication, bridge: NativeBridge, dialogs: UITestDialogs, output: URL) {
        self.app = app; self.bridge = bridge; self.dialogs = dialogs; self.output = output
    }

    func run() async throws {
        try await wait("document.querySelectorAll('.figure-panel').length === 6")
        try check(app.window.isVisible, "actual Cocoa window visible with bundled offline frontend")
        try await snapshot("blank-native-workbench.png")
        let pdf = output.appendingPathComponent("Synthetic vector pages.pdf")
        let png = output.appendingPathComponent("Synthetic RGB image.png")
        let tiff = output.appendingPathComponent("Synthetic RGB image.tiff")
        try makePDF().write(to: pdf)
        let image = makeImage()
        try NativeRendering.encode(image, type: .png, dpi: 300).write(to: png)
        try NativeRendering.encode(image, type: .tiff, dpi: 300).write(to: tiff)
        dialogs.imports = [pdf, png, tiff]
        try menu("import")
        try await wait("document.querySelectorAll('.source-item').length === 3 && document.querySelector('.app-shell').getAttribute('aria-busy') === 'false'")
        try await wait("[...document.querySelectorAll('.source-item img.page-preview')].filter(i=>i.complete&&i.naturalWidth>0).length === 3")
        try check(true, "native import and real PDF/PNG/TIFF source previews")
        try await click("button[aria-label='Place Synthetic vector pages.pdf']")
        try await wait("document.querySelectorAll('.page-choice').length === 2")
        try await click(".page-choice:nth-child(2)")
        try await button("Place page 2")
        try await wait("document.querySelector('[data-row=\"0\"][data-column=\"0\"]').getAttribute('aria-label').includes('page 2')")
        try await click("[data-row='0'][data-column='1']")
        try await click("button[aria-label='Place Synthetic RGB image.png']")
        try await wait("document.querySelectorAll('.figure-panel.has-source').length === 2")
        try menu("undo")
        try await wait("document.querySelectorAll('.figure-panel.has-source').length === 1")
        try check(try await evaluate("document.querySelector('[data-row=\"0\"][data-column=\"0\"]').dataset.assetId !== ''") as? Bool == true,
                  "actual native Undo menu applies exactly one layout operation")
        try menu("redo")
        try await wait("document.querySelectorAll('.figure-panel.has-source').length === 2")
        try check(true, "actual native Redo menu restores exactly one operation")
        try await click("[data-row='0'][data-column='2']")
        try await click("button[aria-label='Place Synthetic RGB image.tiff']")
        try await wait("document.querySelectorAll('.figure-panel.has-source').length === 3")
        try await wait("[...document.querySelectorAll('.figure-panel.has-source img.page-preview')].every(i=>i.complete&&i.naturalWidth>0)")

        app.window.performClose(nil)
        try await waitSheet()
        try alertButton("Cancel")
        try await pause()
        try check(app.window.isVisible && app.window.isDocumentEdited, "dirty Close Cancel preserves open document")
        dialogs.saving = nil
        app.window.performClose(nil)
        try await waitSheet(); try alertButton("Save")
        try await wait("document.querySelector('.app-shell').getAttribute('aria-busy') === 'false'")
        try await pause()
        try check(app.window.isVisible && app.window.isDocumentEdited, "dirty Close Save cancellation keeps window open")

        let project = output.appendingPathComponent("Native integration.figureassembly")
        dialogs.saving = project
        holdNextCleanState()
        try menu("save")
        try await wait("document.body.innerText.includes('Project saved')")
        try await waitNative("the native saved-state callback", diagnostics: { self.saveDiagnostics(project) }) {
            self.heldCleanState != nil
        }
        try check(FileManager.default.fileExists(atPath: project.path) && app.window.isDocumentEdited,
                  "save notice can precede the deliberately delayed native clean callback")
        let cleanState = heldCleanState
        heldCleanState = nil
        let cleanStateRelease = Task { @MainActor in
            try await Task.sleep(for: .milliseconds(300))
            cleanState?()
        }
        try await waitNative("the saved file and native clean flag", diagnostics: { self.saveDiagnostics(project) }) {
            FileManager.default.fileExists(atPath: project.path) && !self.app.window.isDocumentEdited
        }
        try await cleanStateRelease.value
        try check(FileManager.default.fileExists(atPath: project.path) && !app.window.isDocumentEdited,
                  "real native Save writes portable project and marks clean")
        try await click(".labels-button")
        try await pause()
        try Data("EXTERNAL CHANGE: PRESERVE THIS FILE".utf8).write(to: project)
        app.window.performClose(nil)
        try await waitSheet(); try alertButton("Save")
        try await wait("document.body.innerText.includes('changed outside')")
        try check(app.window.isVisible && app.window.isDocumentEdited, "dirty Close failed Save keeps window open")
        try check(try String(contentsOf: project, encoding: .utf8) == "EXTERNAL CHANGE: PRESERVE THIS FILE", "UI conflict leaves external bytes intact")
        try await click(".labels-button")
        let recovered = output.appendingPathComponent("Recovered native integration.figureassembly")
        dialogs.saving = recovered
        try menu("saveAs")
        try await wait("document.body.innerText.includes('Project saved') && !document.body.innerText.includes('changed outside')")
        try await waitNative("the Save As file and native clean flag", diagnostics: { self.saveDiagnostics(recovered) }) {
            FileManager.default.fileExists(atPath: recovered.path) && !self.app.window.isDocumentEdited
        }
        try check(FileManager.default.fileExists(atPath: recovered.path), "native Save As recovers after conflict")

        try menu("new")
        try await wait("document.querySelectorAll('.source-item').length === 0")
        dialogs.opening = recovered
        try menu("open")
        try await wait("document.querySelectorAll('.source-item').length === 3 && document.querySelectorAll('.figure-panel.has-source').length === 3")
        try await wait("[...document.querySelectorAll('img.page-preview')].every(i=>i.complete&&i.naturalWidth>0)")
        try check(true, "native Open restores source bytes, TIFF verification and mixed previews")
        dialogs.saving = output.appendingPathComponent("Native composed.pdf")
        try menu("export")
        try await wait("document.querySelector('.notice[role=status]')?.innerText.startsWith('Exported.') === true && document.querySelector('.app-shell').getAttribute('aria-busy') === 'false'")
        let composed = try Data(contentsOf: dialogs.saving!)
        try check(try NativeRendering.pdf(composed).numberOfPages == 1, "actual native Export menu writes composed PDF")
        try await snapshot("mixed-native-workbench.png")
        try await click("button[aria-label='Export options']")
        try await wait("document.querySelector('dialog[open]') !== null")
        _ = try await evaluate("(() => {const s=document.querySelector('.export-form select');s.value='png';s.dispatchEvent(new Event('change',{bubbles:true}));return true})()")
        try await wait("document.querySelector('dialog[open]').innerText.includes('Export PNG')")
        dialogs.saving = output.appendingPathComponent("Native composed.png")
        try await button("Export PNG")
        try await wait("document.querySelector('.notice[role=status]')?.innerText.startsWith('Exported.') === true && document.querySelector('.app-shell').getAttribute('aria-busy') === 'false' && document.querySelector('dialog[open]') === null")
        try check(FileManager.default.fileExists(atPath: dialogs.saving!.path), "native auxiliary PNG export through real frontend bridge")

        let current = app.webView.url
        _ = try await evaluate("window.location.href='https://example.invalid/blocked'; true")
        try await pause()
        try check(app.webView.url == current, "external main-frame navigation denied")
        let fetchBlocked = try await app.webView.callAsyncJavaScript("try {await fetch('https://example.invalid/blocked');return false} catch {return true}", arguments: [:], in: nil, contentWorld: .page)
        try check(fetchBlocked as? Bool == true, "external fetch blocked by offline policy")
        let report: [String: Any] = ["status": "PASS", "assertions": assertions, "count": assertions.count,
                                     "resources": app.webView.url?.path ?? "", "snapshot": "mixed-native-workbench.png",
                                     "scope": "Actual WKWebView/AppKit bridge and NSMenu actions; injected native dialog selections; synthetic fixtures only."]
        try JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys]).write(to: output.appendingPathComponent("native-ui-report.json"))
        print("\(assertions.count) native UI integration assertions passed")
    }

    func evaluate(_ script: String) async throws -> Any { try await app.webView.evaluateJavaScript(script) ?? NSNull() }
    func pause() async throws { try await Task.sleep(for: .milliseconds(200)) }
    func check(_ condition: Bool, _ name: String) throws {
        guard condition else { throw UITestError.failed(name) }
        assertions.append(name); print("PASS \(name)")
    }
    func wait(_ script: String) async throws {
        for _ in 0..<200 {
            if let web = app.webView, web.url != nil, (try? await evaluate(script)) as? Bool == true { return }
            try await Task.sleep(for: .milliseconds(100))
        }
        let body = (try? await evaluate("document.body.innerText")) ?? "No document"
        throw UITestError.failed("Timed out: \(script)\n\(body)")
    }
    func waitNative(_ description: String, diagnostics: () -> String, predicate: () -> Bool) async throws {
        for _ in 0..<100 {
            if predicate() { return }
            try await Task.sleep(for: .milliseconds(100))
        }
        throw UITestError.failed("Timed out waiting for \(description): \(diagnostics())")
    }
    private func saveDiagnostics(_ path: URL) -> String {
        "fileExists=\(FileManager.default.fileExists(atPath: path.path)), nativeDirty=\(app.window.isDocumentEdited), windowVisible=\(app.window.isVisible), heldCleanCallback=\(heldCleanState != nil), file=\(path.path)"
    }
    private func holdNextCleanState() {
        // Deliberately reproduce React's notice rendering before the asynchronous native
        // setDocumentState callback. Only this test's callback is gated; production is unchanged.
        let forward = bridge.documentState
        bridge.documentState = { [weak self] title, dirty in
            guard let self else { return }
            if dirty { forward?(title, dirty); return }
            self.bridge.documentState = forward
            self.heldCleanState = { forward?(title, dirty) }
        }
    }
    func click(_ selector: String) async throws {
        let data = try JSONSerialization.data(withJSONObject: selector, options: [.fragmentsAllowed])
        _ = try await evaluate("(() => { const e=document.querySelector(\(String(data:data,encoding:.utf8)!)); if(!e)throw Error('Missing element'); e.click(); return true })()")
        try await pause()
    }
    func button(_ text: String) async throws {
        let data = try JSONSerialization.data(withJSONObject: text, options: [.fragmentsAllowed])
        _ = try await evaluate("(() => { const e=[...document.querySelectorAll('button')].find(e=>e.textContent.trim()===\(String(data:data,encoding:.utf8)!));if(!e)throw Error('Missing button');e.click();return true })()")
        try await pause()
    }
    func menu(_ action: String) throws {
        func find(_ menu: NSMenu) -> (NSMenu, Int)? {
            for (index, item) in menu.items.enumerated() {
                if item.representedObject as? String == action { return (menu, index) }
                if let submenu = item.submenu, let result = find(submenu) { return result }
            }
            return nil
        }
        guard let root = NSApp.mainMenu, let (menu, index) = find(root) else { throw UITestError.failed("Missing native menu \(action)") }
        menu.performActionForItem(at: index)
    }
    func waitSheet() async throws {
        for _ in 0..<30 { if app.window.attachedSheet != nil { return }; try await pause() }
        throw UITestError.failed("Missing dirty document sheet")
    }
    func alertButton(_ title: String) throws {
        func find(_ view: NSView) -> NSButton? {
            if let button = view as? NSButton, button.title == title { return button }
            for subview in view.subviews { if let button = find(subview) { return button } }
            return nil
        }
        guard let content = app.window.attachedSheet?.contentView, let button = find(content) else { throw UITestError.failed("Missing alert \(title)") }
        button.performClick(nil)
    }
    func snapshot(_ name: String) async throws {
        let image = try await app.webView.takeSnapshot(configuration: nil)
        guard let tiff = image.tiffRepresentation, let bitmap = NSBitmapImageRep(data: tiff),
              let png = bitmap.representation(using: .png, properties: [:]) else { throw UITestError.failed("Snapshot encoding") }
        try png.write(to: output.appendingPathComponent(name))
    }
    func makePDF() -> Data {
        let bytes = NSMutableData(); var bounds = CGRect(x: 0, y: 0, width: 120, height: 100)
        let context = CGContext(consumer: CGDataConsumer(data: bytes as CFMutableData)!, mediaBox: &bounds, nil)!
        for index in 0..<2 {
            context.beginPDFPage(nil); context.setFillColor(CGColor(gray: 1, alpha: 1)); context.fill(bounds)
            context.setFillColor(CGColor(red: index == 0 ? 0.1 : 0.8, green: 0.25, blue: 0.6, alpha: 1))
            context.fill(CGRect(x: 16, y: 18, width: 88, height: index == 0 ? 64 : 44))
            context.endPDFPage()
        }
        context.closePDF(); return bytes as Data
    }
    func makeImage() -> CGImage {
        let context = CGContext(data: nil, width: 240, height: 150, bitsPerComponent: 8, bytesPerRow: 960,
                                space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
        context.setFillColor(CGColor(red: 0.15, green: 0.55, blue: 0.4, alpha: 1)); context.fill(CGRect(x: 0, y: 0, width: 240, height: 150))
        return context.makeImage()!
    }
}

@main
struct NativeUITest {
    @MainActor static func main() throws {
        guard CommandLine.arguments.count == 3 else { throw UITestError.failed("native-ui DIST EVIDENCE") }
        let resources = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
        let output = URL(fileURLWithPath: CommandLine.arguments[2], isDirectory: true)
        try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)
        for name in ["native-ui-report.json", "native-ui-error.txt", "mixed-native-workbench.png", "blank-native-workbench.png"] {
            try? FileManager.default.removeItem(at: output.appendingPathComponent(name))
        }
        let dialogs = UITestDialogs()
        let bridge = NativeBridge(dialogs: dialogs)
        let delegate = AssemblyApplication(bundledWebRoot: resources, bridge: bridge)
        let app = NSApplication.shared; app.setActivationPolicy(.regular); app.delegate = delegate
        Task { @MainActor in
            do { try await NativeUIRun(app: delegate, bridge: bridge, dialogs: dialogs, output: output).run(); exit(0) }
            catch {
                let report = "FAIL \(error)\n"
                try? Data(report.utf8).write(to: output.appendingPathComponent("native-ui-error.txt"))
                print(report); exit(1)
            }
        }
        app.run()
    }
}
