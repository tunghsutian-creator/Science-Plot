import AppKit
import UniformTypeIdentifiers
import WebKit

@MainActor
final class NativeBridge: NSObject, WKScriptMessageHandler {
    weak var webView: WKWebView?
    weak var window: NSWindow? { didSet { dialogs.window = window } }
    var documentState: ((String, Bool) -> Void)?
    var saveFinished: ((Bool) -> Void)?
    private let files = ProjectFiles()
    private let renderer = NativeRenderWorker()
    private var active = Set<String>()
    private let dialogs: any NativeDialogs

    init(dialogs: any NativeDialogs = SystemDialogs()) { self.dialogs = dialogs }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.frameInfo.isMainFrame else { return }
        do {
            let request = try BridgeRequest(message.body)
            guard !active.contains(request.id), active.count < 32 else {
                throw NativeFailure("bridge_busy", "Too many pending native requests. Try again shortly.")
            }
            active.insert(request.id)
            Task { @MainActor in
                defer { active.remove(request.id) }
                do { reply(request.id, result: try await handle(request)) }
                catch {
                    if request.method == "saveProject" { saveFinished?(false) }
                    reply(request.id, error: error)
                }
            }
        } catch {
            if let body = message.body as? [String: Any], let id = body["id"] as? String, id.count <= 128 {
                reply(id, error: error)
            }
        }
    }

    func handle(_ request: BridgeRequest) async throws -> Any {
        switch request.method {
        case "setDocumentState":
            try request.keys(["title", "dirty"])
            let title = try request.string("title", maximum: 512)
            documentState?(title, try request.boolean("dirty"))
            return NSNull()
        case "importFiles":
            try request.keys([])
            let urls = try await dialogs.importFiles()
            guard urls.count <= 64 else { throw NativeFailure("too_many_files", "Import up to 64 files at once.") }
            let data = try await renderer.importFiles(urls)
            return try JSONSerialization.jsonObject(with: data)
        case "openProject":
            try request.keys([])
            guard let url = try await dialogs.openProject() else { return NSNull() }
            return try files.open(url)
        case "saveProject":
            return try await saveProject(request)
        case "saveExport":
            return try await saveExport(request)
        case "previewPdf":
            try request.keys(["bytesBase64", "pageIndex", "maxPixels"])
            let bytes = try decodeBase64(request.string("bytesBase64", maximum: NativeLimits.sourceBytes * 2), maximum: NativeLimits.sourceBytes)
            let index = try request.integer("pageIndex", range: 0...9999)
            let pixels = try request.integer("maxPixels", range: 1...NativeLimits.previewPixels)
            return try await renderer.preview(bytes, pageIndex: index, maxPixels: pixels)
        default:
            throw NativeFailure("unknown_method", "This native action is not supported.")
        }
    }

    private func saveProject(_ request: BridgeRequest) async throws -> Any {
        try request.keys(["text", "name"], optional: ["token"])
        let text = try request.string("text", maximum: NativeLimits.projectBytes)
        let name = try request.string("name", maximum: 512)
        var token: String?
        if request.params["token"] != nil { token = try request.string("token", maximum: 128) }
        var destination: URL?
        if token == nil {
            destination = try await dialogs.saveFile(name: safeFilename(name, extension: "figureassembly"), type: UTType(filenameExtension: "figureassembly") ?? .json)
            guard destination != nil else { saveFinished?(false); return ["cancelled": true] }
        }
        let result = try files.save(text, token: token, destination: destination)
        saveFinished?(true)
        return result
    }

    private func saveExport(_ request: BridgeRequest) async throws -> Any {
        try request.keys(["bytesBase64", "name", "format", "dpi"])
        let bytes = try decodeBase64(request.string("bytesBase64", maximum: NativeLimits.sourceBytes * 2), maximum: NativeLimits.sourceBytes)
        let name = try request.string("name", maximum: 512)
        let format = try request.string("format", maximum: 8)
        guard ["pdf", "png", "tiff"].contains(format) else { throw NativeFailure("export_format", "Choose PDF, PNG or TIFF.") }
        let dpi = try request.integer("dpi", range: 72...1200)
        let rendered = try await renderer.export(bytes, format: format, dpi: dpi)
        let type: UTType = format == "pdf" ? .pdf : format == "png" ? .png : .tiff
        guard let destination = try await dialogs.saveFile(name: safeFilename(name, extension: format), type: type) else {
            return ["cancelled": true]
        }
        let expected = try ProjectFiles.existingSnapshot(destination)
        try await Task.detached(priority: .userInitiated) {
            try ProjectFiles.replace(rendered, at: destination, expected: expected)
        }.value
        return ["cancelled": false, "name": destination.lastPathComponent]
    }

    private func reply(_ id: String, result: Any) { send(["id": id, "result": result]) }
    private func reply(_ id: String, error: Error) {
        let failure = error as? NativeFailure
        send(["id": id, "error": ["code": failure?.code ?? "native_error", "message": failure?.message ?? error.localizedDescription]])
    }
    private func send(_ object: [String: Any]) {
        guard let data = try? JSONSerialization.data(withJSONObject: object, options: [.fragmentsAllowed]),
              let json = String(data: data, encoding: .utf8) else { return }
        webView?.evaluateJavaScript("window.__assemblyReply(\(json))", completionHandler: nil)
    }
}
