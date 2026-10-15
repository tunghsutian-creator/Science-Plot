import Foundation

/// Serial background decoding bounds simultaneous raster memory without blocking AppKit.
actor NativeRenderWorker {
    func importFiles(_ urls: [URL]) throws -> Data {
        var total = 0
        var results: [[String: Any]] = []
        for url in urls {
            let properties = try url.resourceValues(forKeys: [.fileSizeKey])
            let size = properties.fileSize ?? NativeLimits.sourceBytes + 1
            guard size <= NativeLimits.sourceBytes, total <= NativeLimits.projectBytes - size else {
                throw NativeFailure("import_too_large", "Import fewer files at once. This selection exceeds the supported size.")
            }
            total += size
            results.append(try NativeRendering.importFile(url))
        }
        return try JSONSerialization.data(withJSONObject: results)
    }

    func preview(_ bytes: Data, pageIndex: Int, maxPixels: Int) throws -> String {
        try NativeRendering.preview(bytes, pageIndex: pageIndex, maxPixels: maxPixels)
    }

    func export(_ bytes: Data, format: String, dpi: Int) throws -> Data {
        try NativeRendering.export(bytes, format: format, dpi: dpi)
    }
}
