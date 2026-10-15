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
            guard let image = CGImageSourceCreateImageAtIndex(source, 0, nil),
                  image.width == width, image.height == height else {
                throw NativeFailure("image_decode", "The TIFF could not be decoded without changing its dimensions.")
            }
            result["normalizedPngBase64"] = try encode(image, type: .png, dpi: nil).base64EncodedString()
        }
        return result
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
        return bytes as Data
    }
}
