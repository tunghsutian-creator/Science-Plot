import CoreGraphics
import Foundation
import ImageIO
import UniformTypeIdentifiers

enum NativeRendering {
    static func importFile(_ url: URL) throws -> [String: Any] {
        let (bytes, _) = try ProjectFiles.read(url, maximum: NativeLimits.sourceBytes)
        let suffix = url.pathExtension.lowercased()
        var result: [String: Any] = ["name": url.lastPathComponent, "bytesBase64": bytes.base64EncodedString()]
        if suffix == "pdf" { _ = try pdf(bytes); return result }
        let isTIFF = suffix == "tif" || suffix == "tiff"
        if isTIFF && (bytes.starts(with: [0x49, 0x49, 0x2b, 0]) || bytes.starts(with: [0x4d, 0x4d, 0, 0x2b])) {
            throw NativeFailure("unsupported_tiff", "BigTIFF is not supported. Export a standard single-image TIFF or PNG.")
        }
        guard ["png", "jpg", "jpeg", "tif", "tiff"].contains(suffix),
              let source = CGImageSourceCreateWithData(bytes as CFData, nil) else {
            throw NativeFailure("unsupported_image", "Choose a PDF, PNG, JPEG or single-image TIFF.")
        }
        let expected: UTType = isTIFF ? .tiff : suffix == "png" ? .png : .jpeg
        guard let actual = CGImageSourceGetType(source), actual as String == expected.identifier else {
            throw NativeFailure("image_type", "The image bytes do not match the filename extension.")
        }
        guard CGImageSourceGetCount(source) == 1 else {
            throw NativeFailure("multiple_images", "Multiple-image files are not supported. Export one image per file.")
        }
        guard let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
              let width = properties[kCGImagePropertyPixelWidth] as? Int,
              let height = properties[kCGImagePropertyPixelHeight] as? Int,
              width > 0, height > 0, width <= 32768, height <= 32768,
              width <= NativeLimits.rasterPixels / height else {
            throw NativeFailure("image_too_large", "Image dimensions exceed the 64-million-pixel limit.")
        }
        let orientation = (properties[kCGImagePropertyOrientation] as? NSNumber)?.intValue ?? 1
        guard orientation == 1 else {
            throw NativeFailure("image_orientation", "This image has an orientation transform. Export an upright PNG or TIFF first.")
        }
        result["pixelWidth"] = width; result["pixelHeight"] = height
        if let dpi = try imageDPI(properties) { result["dpi"] = dpi }
        if isTIFF {
            let image = try decodeTIFF(bytes)
            result["normalizedPngBase64"] = try encode(image, type: .png, dpi: nil).base64EncodedString()
        }
        return result
    }

    static func decodeTIFF(_ bytes: Data) throws -> CGImage {
        guard !(bytes.starts(with: [0x49, 0x49, 0x2b, 0]) || bytes.starts(with: [0x4d, 0x4d, 0, 0x2b])) else {
            throw NativeFailure("unsupported_tiff", "BigTIFF is not supported.")
        }
        try rejectTIFFProfile(bytes)
        guard let source = CGImageSourceCreateWithData(bytes as CFData, nil),
              CGImageSourceGetType(source) as String? == UTType.tiff.identifier,
              CGImageSourceGetCount(source) == 1,
              let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
              let width = properties[kCGImagePropertyPixelWidth] as? Int,
              let height = properties[kCGImagePropertyPixelHeight] as? Int,
              properties[kCGImagePropertyDepth] as? Int == 8,
              properties[kCGImagePropertyProfileName] == nil,
              width > 0, height > 0, width <= 32768, height <= 32768,
              width <= NativeLimits.rasterPixels / height,
              (properties[kCGImagePropertyOrientation] as? NSNumber)?.intValue ?? 1 == 1,
              let image = CGImageSourceCreateImageAtIndex(source, 0, nil),
              image.width == width, image.height == height, image.bitsPerComponent == 8,
              image.colorSpace?.model == .rgb || image.colorSpace?.model == .monochrome else {
            throw NativeFailure("unsupported_tiff", "Use an upright, single-image, 8-bit grayscale or RGB TIFF.")
        }
        return image
    }

    private static func rejectTIFFProfile(_ bytes: Data) throws {
        let little = bytes.first == 0x49
        func number(_ offset: Int, _ count: Int) -> Int? {
            guard offset >= 0, offset <= bytes.count - count else { return nil }
            let values = little ? Array(bytes[offset..<offset + count].reversed()) : Array(bytes[offset..<offset + count])
            return values.reduce(0) { $0 * 256 + Int($1) }
        }
        guard let offset = number(4, 4), let count = number(offset, 2), count <= 4096 else { return }
        for index in 0..<count {
            if number(offset + 2 + index * 12, 2) == 34675 {
                throw NativeFailure("tiff_profile", "TIFFs with embedded color profiles are not supported. Keep the original and export a standard sRGB PNG.")
            }
        }
    }

    static func verifyTIFF(_ bytes: Data, normalizedPNG: Data) throws {
        let original = try decodeTIFF(bytes)
        guard let source = CGImageSourceCreateWithData(normalizedPNG as CFData, nil),
              CGImageSourceGetType(source) as String? == UTType.png.identifier,
              CGImageSourceGetCount(source) == 1,
              let supplied = CGImageSourceCreateImageAtIndex(source, 0, nil),
              supplied.width == original.width, supplied.height == original.height,
              supplied.bitsPerComponent == 8,
              supplied.colorSpace?.model == .rgb || supplied.colorSpace?.model == .monochrome,
              try canonicalRGBA(supplied) == canonicalRGBA(original) else {
            throw NativeFailure("tiff_pixels_mismatch", "The saved TIFF preview does not match its original pixels. Reimport the original TIFF.")
        }
    }

    private static func canonicalRGBA(_ image: CGImage) throws -> Data {
        guard let colorSpace = CGColorSpace(name: CGColorSpace.sRGB),
              let context = CGContext(data: nil, width: image.width, height: image.height, bitsPerComponent: 8,
                                      bytesPerRow: image.width * 4, space: colorSpace,
                                      bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else {
            throw NativeFailure("image_decode", "The image pixels could not be verified.")
        }
        context.setBlendMode(.copy)
        context.draw(image, in: CGRect(x: 0, y: 0, width: image.width, height: image.height))
        guard let pixels = context.data else { throw NativeFailure("image_decode", "The image pixels could not be read.") }
        return Data(bytes: pixels, count: image.width * image.height * 4)
    }

    static func imageDPI(_ properties: [CFString: Any]) throws -> Double? {
        let x = (properties[kCGImagePropertyDPIWidth] as? NSNumber)?.doubleValue
        let y = (properties[kCGImagePropertyDPIHeight] as? NSNumber)?.doubleValue
        let validX = x.flatMap { $0.isFinite && $0 > 0 ? $0 : nil }
        let validY = y.flatMap { $0.isFinite && $0 > 0 ? $0 : nil }
        if let validX, let validY {
            guard abs(validX - validY) <= max(0.01, validX * 0.0001) else {
                throw NativeFailure("anisotropic_dpi", "Different horizontal and vertical image resolutions are not supported. Export with square pixels.")
            }
            return validX
        }
        return validX ?? validY
    }

    static func pdf(_ bytes: Data) throws -> CGPDFDocument {
        guard let provider = CGDataProvider(data: bytes as CFData), let document = CGPDFDocument(provider),
              document.numberOfPages > 0 else {
            throw NativeFailure("invalid_pdf", "This file is not a readable PDF.")
        }
        guard !document.isEncrypted || document.isUnlocked else {
            throw NativeFailure("encrypted_pdf", "Encrypted PDFs must be exported unlocked before import.")
        }
        return document
    }

    static func pageGeometry(_ page: CGPDFPage) throws -> CGSize {
        let bounds = page.getBoxRect(.cropBox).intersection(page.getBoxRect(.mediaBox))
        guard !bounds.isNull, bounds.width.isFinite, bounds.height.isFinite,
              bounds.width > 0, bounds.height > 0 else {
            throw NativeFailure("invalid_pdf_bounds", "The PDF page has invalid visible bounds.")
        }
        let rotation = ((page.rotationAngle % 360) + 360) % 360
        guard rotation % 90 == 0 else { throw NativeFailure("pdf_rotation", "The PDF page has an unsupported rotation.") }
        return rotation == 90 || rotation == 270
            ? CGSize(width: bounds.height, height: bounds.width) : bounds.size
    }

    static func rasterPage(_ bytes: Data, pageIndex: Int, longEdge: Int? = nil, dpi: Int? = nil) throws -> CGImage {
        let document = try pdf(bytes)
        guard pageIndex >= 0, pageIndex < document.numberOfPages, let page = document.page(at: pageIndex + 1) else {
            throw NativeFailure("pdf_page", "The selected PDF page does not exist.")
        }
        let size = try pageGeometry(page)
        let scale: Double
        if let longEdge { scale = Double(longEdge) / max(size.width, size.height) }
        else if let dpi { scale = Double(dpi) / 72 }
        else { throw NativeFailure("raster_size", "Choose a raster resolution.") }
        let pixelWidth = ceil(size.width * scale), pixelHeight = ceil(size.height * scale)
        guard pixelWidth >= 1, pixelHeight >= 1, pixelWidth <= 32768, pixelHeight <= 32768,
              pixelWidth * pixelHeight <= Double(NativeLimits.rasterPixels) else {
            throw NativeFailure("raster_too_large", "This resolution exceeds the 64-million-pixel export limit. Choose a lower DPI.")
        }
        let width = Int(pixelWidth), height = Int(pixelHeight)
        guard let context = CGContext(data: nil, width: width, height: height, bitsPerComponent: 8,
                                      bytesPerRow: width * 4, space: CGColorSpaceCreateDeviceRGB(),
                                      bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else {
            throw NativeFailure("raster_memory", "The raster image could not be allocated. Choose a lower DPI.")
        }
        context.setFillColor(CGColor(gray: 1, alpha: 1))
        context.fill(CGRect(x: 0, y: 0, width: width, height: height))
        let target = CGRect(x: 0, y: 0, width: width, height: height)
        context.clip(to: target)
        context.concatenate(page.getDrawingTransform(.cropBox, rect: target, rotate: 0, preserveAspectRatio: true))
        context.drawPDFPage(page)
        guard let image = context.makeImage() else { throw NativeFailure("raster_render", "The PDF raster could not be created.") }
        return image
    }

    static func preview(_ bytes: Data, pageIndex: Int, maxPixels: Int) throws -> String {
        let image = try rasterPage(bytes, pageIndex: pageIndex, longEdge: maxPixels)
        return "data:image/png;base64," + (try encode(image, type: .png, dpi: nil)).base64EncodedString()
    }

    static func export(_ bytes: Data, format: String, dpi: Int) throws -> Data {
        if format == "pdf" { _ = try pdf(bytes); return bytes }
        guard ["png", "tiff"].contains(format), (72...1200).contains(dpi) else {
            throw NativeFailure("export_format", "Choose PDF, PNG or TIFF at 72–1200 DPI.")
        }
        guard try pdf(bytes).numberOfPages == 1 else {
            throw NativeFailure("export_pages", "Raster export requires a single composed page.")
        }
        let image = try rasterPage(bytes, pageIndex: 0, dpi: dpi)
        return try encode(image, type: format == "png" ? .png : .tiff, dpi: dpi)
    }

    static func encode(_ image: CGImage, type: UTType, dpi: Int?) throws -> Data {
        let bytes = NSMutableData()
        guard let destination = CGImageDestinationCreateWithData(bytes, type.identifier as CFString, 1, nil) else {
            throw NativeFailure("image_encode", "The image encoder is unavailable.")
        }
        var properties: [CFString: Any] = [:]
        if let dpi { properties[kCGImagePropertyDPIWidth] = dpi; properties[kCGImagePropertyDPIHeight] = dpi }
        CGImageDestinationAddImage(destination, image, properties as CFDictionary)
        guard CGImageDestinationFinalize(destination) else { throw NativeFailure("image_encode", "The image could not be encoded.") }
        // ImageIO adds benign ColorSpace/dimension EXIF even for an upright CGImage.
        // Only this freshly generated metadata is removed; original import bytes are immutable.
        return type == .png ? try withoutGeneratedEXIF(bytes as Data) : bytes as Data
    }

    private static func withoutGeneratedEXIF(_ bytes: Data) throws -> Data {
        var result = Data(bytes.prefix(8)), offset = 8
        while offset + 12 <= bytes.count {
            let length = bytes[offset..<offset + 4].reduce(0) { $0 * 256 + Int($1) }
            guard length <= bytes.count - offset - 12 else { throw NativeFailure("image_encode", "The PNG encoder returned invalid chunks.") }
            let type = String(data: bytes[offset + 4..<offset + 8], encoding: .ascii)
            if type != "eXIf" { result.append(bytes[offset..<offset + length + 12]) }
            offset += length + 12
        }
        guard offset == bytes.count else { throw NativeFailure("image_encode", "The PNG encoder returned incomplete chunks.") }
        return result
    }
}
