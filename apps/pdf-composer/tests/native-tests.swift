import AppKit
import CoreGraphics
import Foundation
import ImageIO
import UniformTypeIdentifiers

enum TestFailure: Error { case assertion(String) }

@MainActor
final class FixtureDialogs: NativeDialogs {
    weak var window: NSWindow?
    var imports: [URL] = []
    var opening: URL?
    var saving: URL?
    func importFiles() async throws -> [URL] { imports }
    func openProject() async throws -> URL? { opening }
    func saveFile(name: String, type: UTType) async throws -> URL? { saving }
}

@main
struct NativeTests {
    @MainActor static func main() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("figure-native-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        var passed = 0
        func check(_ condition: Bool, _ name: String) throws {
            guard condition else { throw TestFailure.assertion(name) }
            passed += 1; FileHandle.standardOutput.write(Data("PASS \(name)\n".utf8))
        }
        func failure(_ code: String, _ body: () throws -> Void) throws {
            do { try body(); throw TestFailure.assertion("expected \(code)") }
            catch let error as NativeFailure { try check(error.code == code, "refuses \(code)") }
        }

        let files = ProjectFiles(), path = directory.appendingPathComponent("layout.figureassembly")
        let saved = try files.save("{\"version\":1}", token: nil, destination: path)
        let token = saved["token"] as! String
        try check(try String(contentsOf: path, encoding: .utf8) == "{\"version\":1}", "initial portable save")
        _ = try files.save("{\"version\":2}", token: token, destination: nil)
        try check(try String(contentsOf: path, encoding: .utf8) == "{\"version\":2}", "same-session repeated save")
        let opened = try files.open(path)
        try check(opened["text"] as? String == "{\"version\":2}", "open preserves exact UTF-8 bytes")
        try Data("{\"external\":true}".utf8).write(to: path)
        try failure("save_conflict") { _ = try files.save("overwrite", token: token, destination: nil) }
        try check(try String(contentsOf: path, encoding: .utf8) == "{\"external\":true}", "conflict preserves external bytes")
        try failure("unknown_save_token") { _ = try files.save("x", token: "foreign-session", destination: nil) }
        let alias = directory.appendingPathComponent("alias.figureassembly")
        try FileManager.default.createSymbolicLink(at: alias, withDestinationURL: path)
        try failure("file_read") { _ = try files.open(alias) }
        try failure("file_read") { _ = try files.save("overwrite", token: nil, destination: alias) }
        try check(try String(contentsOf: path, encoding: .utf8) == "{\"external\":true}", "save alias preserves original")
        let temps = try FileManager.default.contentsOfDirectory(atPath: directory.path).filter { $0.hasPrefix(".figure-assembly-") }
        try check(temps.isEmpty, "atomic-save temporary files cleaned")

        let pdf = makePDF()
        try check(try NativeRendering.export(pdf, format: "pdf", dpi: 300) == pdf, "PDF export bytes unchanged")
        let preview = try NativeRendering.preview(pdf, pageIndex: 0, maxPixels: 160)
        let previewBytes = Data(base64Encoded: String(preview.dropFirst("data:image/png;base64,".count)))!
        let previewSource = CGImageSourceCreateWithData(previewBytes as CFData, nil)!
        let previewImage = CGImageSourceCreateImageAtIndex(previewSource, 0, nil)!
        try check(previewImage.width == 80 && previewImage.height == 160, "preview honors crop box and intrinsic rotation")
        for format in ["png", "tiff"] {
            let data = try NativeRendering.export(pdf, format: format, dpi: 144)
            let source = CGImageSourceCreateWithData(data as CFData, nil)!
            let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil)! as NSDictionary
            try check(properties[kCGImagePropertyPixelWidth] as? Int == 100 && properties[kCGImagePropertyPixelHeight] as? Int == 200,
                      "\(format) export physical dimensions")
            let dpi = (properties[kCGImagePropertyDPIWidth] as! NSNumber).doubleValue
            try check(abs(dpi - 144) < 0.1, "\(format) export DPI metadata")
        }
        try failure("pdf_page") { _ = try NativeRendering.preview(pdf, pageIndex: 1, maxPixels: 100) }
        try failure("raster_too_large") { _ = try NativeRendering.rasterPage(makePDF(size: 100000), pageIndex: 0, dpi: 1200) }
        try failure("export_pages") { _ = try NativeRendering.export(makePDF(pages: 2), format: "png", dpi: 144) }
        let fractional = makeMarkedPDF()
        let markedPage = try NativeRendering.pdf(fractional).page(at: 1)!
        let mapped = CGPoint(x: 20, y: 30).applying(try NativeRendering.rasterTransform(markedPage, scale: 2))
        try check(abs(mapped.x - 20) < 0.000001 && abs(mapped.y - 140.5) < 0.000001,
                  "fractional crop/media intersection and rotation preserve exact requested scale")
        let marked = try NativeRendering.rasterPage(fractional, pageIndex: 0, dpi: 144)
        try check(marked.width == 101 && marked.height == 161, "fractional physical raster rounds only bitmap extent")
        let bounds = redBounds(marked)
        // Exact geometry maps to x=[20,40], y=[120.5,140.5]. In the 161-row image,
        // full-red samples occupy rows 21...39; the two half-covered edge rows antialias.
        try check(bounds == CGRect(x: 20, y: 21, width: 20, height: 19),
                  "actual marked PDF pixels retain exact DPI and fractional antialiased edges")

        let image = makeImage()
        let tiff = directory.appendingPathComponent("source.tiff")
        let original = try NativeRendering.encode(image, type: .tiff, dpi: 300)
        try original.write(to: tiff)
        let imported = try NativeRendering.importFile(tiff)
        try check(Data(base64Encoded: imported["bytesBase64"] as! String) == original, "TIFF original bytes preserved")
        try check(imported["pixelWidth"] as? Int == 24 && imported["pixelHeight"] as? Int == 12, "TIFF whole-pixel dimensions preserved")
        let normalized = Data(base64Encoded: imported["normalizedPngBase64"] as! String)!
        let normalizedSource = CGImageSourceCreateWithData(normalized as CFData, nil)!
        let normalizedImage = CGImageSourceCreateImageAtIndex(normalizedSource, 0, nil)!
        try check(rgba(normalizedImage) == rgba(image), "TIFF normalized PNG pixel identity")
        try NativeRendering.verifyTIFF(original, normalizedPNG: normalized)
        try check(true, "TIFF provenance re-decode accepts exact pixels")
        let blueContext = CGContext(data: nil, width: 24, height: 12, bitsPerComponent: 8, bytesPerRow: 96,
                                    space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
        blueContext.setFillColor(CGColor(red: 0, green: 0, blue: 1, alpha: 1)); blueContext.fill(CGRect(x: 0, y: 0, width: 24, height: 12))
        let bluePNG = try NativeRendering.encode(blueContext.makeImage()!, type: .png, dpi: nil)
        try failure("tiff_pixels_mismatch") { try NativeRendering.verifyTIFF(original, normalizedPNG: bluePNG) }
        try check(abs((imported["dpi"] as! Double) - 300) < 0.01, "TIFF physical DPI preserved")
        let profiled = image.copy(colorSpace: CGColorSpace(name: CGColorSpace.displayP3)!)!
        try NativeRendering.encode(profiled, type: .tiff, dpi: 300).write(to: tiff)
        try failure("tiff_profile") { _ = try NativeRendering.importFile(tiff) }
        let multi = NSMutableData()
        let destination = CGImageDestinationCreateWithData(multi, UTType.tiff.identifier as CFString, 2, nil)!
        CGImageDestinationAddImage(destination, image, nil); CGImageDestinationAddImage(destination, image, nil)
        precondition(CGImageDestinationFinalize(destination))
        try (multi as Data).write(to: tiff)
        try failure("multiple_images") { _ = try NativeRendering.importFile(tiff) }
        try Data([0x49, 0x49, 0x2b, 0, 8, 0, 0, 0]).write(to: tiff)
        try failure("unsupported_tiff") { _ = try NativeRendering.importFile(tiff) }
        try NativeRendering.encode(image, type: .png, dpi: nil).write(to: tiff)
        try failure("image_type") { _ = try NativeRendering.importFile(tiff) }
        let oriented = NSMutableData()
        let orientedDestination = CGImageDestinationCreateWithData(oriented, UTType.jpeg.identifier as CFString, 1, nil)!
        CGImageDestinationAddImage(orientedDestination, image, [kCGImagePropertyOrientation: 6] as CFDictionary)
        precondition(CGImageDestinationFinalize(orientedDestination))
        let jpeg = directory.appendingPathComponent("oriented.jpg")
        try (oriented as Data).write(to: jpeg)
        try failure("image_orientation") { _ = try NativeRendering.importFile(jpeg) }
        try failure("anisotropic_dpi") { _ = try NativeRendering.imageDPI([kCGImagePropertyDPIWidth: 300, kCGImagePropertyDPIHeight: 150]) }
        try check(try NativeRendering.imageDPI([:]) == nil, "unknown DPI omitted for explicit frontend fallback")

        try failure("invalid_params") {
            let request = try BridgeRequest(["id": "a", "method": "previewPdf", "params": ["pageIndex": true]])
            _ = try request.integer("pageIndex", range: 0...10)
        }
        try failure("invalid_request") { _ = try BridgeRequest(["id": "a", "method": "openProject", "params": [:], "extra": 1]) }
        let dialogs = FixtureDialogs(), bridge = NativeBridge(dialogs: dialogs)
        let verified = try await bridge.handle(BridgeRequest(["id": "verify", "method": "verifyTiff", "params": ["bytesBase64": original.base64EncodedString(), "normalizedPngBase64": normalized.base64EncodedString()]]))
        try check(verified is NSNull, "TIFF verification bridge returns null")
        do {
            _ = try await bridge.handle(BridgeRequest(["id": "verify-bad", "method": "verifyTiff", "params": ["bytesBase64": original.base64EncodedString(), "normalizedPngBase64": bluePNG.base64EncodedString()]]))
            throw TestFailure.assertion("bridge accepted wrong TIFF pixels")
        } catch let error as NativeFailure { try check(error.code == "tiff_pixels_mismatch", "TIFF bridge refuses same-size substituted pixels") }
        let cancelled = try await bridge.handle(BridgeRequest(["id": "save", "method": "saveProject", "params": ["text": "{}", "name": "Cancelled"]])) as! [String: Any]
        try check(cancelled["cancelled"] as? Bool == true, "native Save As cancellation leaves no file")
        let openedCancelled = try await bridge.handle(BridgeRequest(["id": "open", "method": "openProject", "params": [:]]))
        try check(openedCancelled is NSNull, "native open cancellation")
        let importedCancelled = try await bridge.handle(BridgeRequest(["id": "import", "method": "importFiles", "params": [:]])) as! [Any]
        try check(importedCancelled.isEmpty, "native import cancellation")
        let cancelledExport = try await bridge.handle(BridgeRequest(["id": "export", "method": "saveExport", "params": ["bytesBase64": pdf.base64EncodedString(), "name": "Cancelled", "format": "pdf", "dpi": 300]])) as! [String: Any]
        try check(cancelledExport["cancelled"] as? Bool == true, "native export cancellation")
        print("\(passed) native tests passed")
    }

    static func makePDF(size: Int = 200, pages: Int = 1) -> Data {
        let kids = (0..<pages).map { "\(3 + $0) 0 R" }.joined(separator: " ")
        var objects = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [\(kids)] /Count \(pages) >>"]
        let streamID = 3 + pages
        for _ in 0..<pages {
            objects.append("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 \(size) \(size)] /CropBox [10 20 \(size - 90) \(size - 130)] /Rotate 90 /Contents \(streamID) 0 R /Resources << >> >>")
        }
        let stream = "1 0 0 rg 10 20 50 50 re f 0 0 1 rg 60 20 50 50 re f"
        objects.append("<< /Length \(stream.utf8.count) >>\nstream\n\(stream)\nendstream")
        var text = "%PDF-1.4\n", offsets = [0]
        for (index, object) in objects.enumerated() { offsets.append(text.utf8.count); text += "\(index + 1) 0 obj\n\(object)\nendobj\n" }
        let xref = text.utf8.count
        text += "xref\n0 \(offsets.count)\n0000000000 65535 f \n"
        for offset in offsets.dropFirst() { text += String(format: "%010d 00000 n \n", offset) }
        text += "trailer\n<< /Size \(offsets.count) /Root 1 0 R >>\nstartxref\n\(xref)\n%%EOF\n"
        return Data(text.utf8)
    }

    static func makeMarkedPDF() -> Data {
        let original = String(data: makePDF(), encoding: .utf8)!
        // Rebuild offsets after changing the page dictionary and stream, never patch xrefs.
        let objects = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
                       "<< /Type /Page /Parent 2 0 R /MediaBox [10 20 110.5 70.25] /CropBox [-5 10 90.25 100] /Rotate 90 /Contents 4 0 R /Resources << >> >>"]
        let stream = "1 0 0 rg 20 30 10 10 re f"
        var text = String(original.prefix(9)), offsets = [0]
        for (index, object) in (objects + ["<< /Length \(stream.utf8.count) >>\nstream\n\(stream)\nendstream"]).enumerated() {
            offsets.append(text.utf8.count); text += "\(index + 1) 0 obj\n\(object)\nendobj\n"
        }
        let xref = text.utf8.count
        text += "xref\n0 \(offsets.count)\n0000000000 65535 f \n"
        for offset in offsets.dropFirst() { text += String(format: "%010d 00000 n \n", offset) }
        text += "trailer\n<< /Size \(offsets.count) /Root 1 0 R >>\nstartxref\n\(xref)\n%%EOF\n"
        return Data(text.utf8)
    }

    static func redBounds(_ image: CGImage) -> CGRect {
        let bytes = rgba(image)
        var xs: [Int] = [], ys: [Int] = []
        for y in 0..<image.height { for x in 0..<image.width {
            let offset = (y * image.width + x) * 4
            if bytes[offset] > 220 && bytes[offset + 1] < 30 && bytes[offset + 2] < 30 { xs.append(x); ys.append(y) }
        } }
        guard let left = xs.min(), let right = xs.max(), let top = ys.min(), let bottom = ys.max() else { return .null }
        return CGRect(x: left, y: top, width: right - left + 1, height: bottom - top + 1)
    }

    static func makeImage() -> CGImage {
        let context = CGContext(data: nil, width: 24, height: 12, bitsPerComponent: 8, bytesPerRow: 96,
                                space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
        context.setFillColor(CGColor(red: 0.8, green: 0.1, blue: 0.4, alpha: 1)); context.fill(CGRect(x: 0, y: 0, width: 24, height: 12))
        return context.makeImage()!
    }

    static func rgba(_ image: CGImage) -> Data {
        let context = CGContext(data: nil, width: image.width, height: image.height, bitsPerComponent: 8,
                                bytesPerRow: image.width * 4, space: CGColorSpaceCreateDeviceRGB(),
                                bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
        context.draw(image, in: CGRect(x: 0, y: 0, width: image.width, height: image.height))
        return Data(bytes: context.data!, count: image.width * image.height * 4)
    }
}
