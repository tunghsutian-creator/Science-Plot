import Foundation
import CoreFoundation

struct NativeFailure: Error, LocalizedError {
    let code: String
    let message: String
    var errorDescription: String? { message }
    init(_ code: String, _ message: String) { self.code = code; self.message = message }
}

enum NativeLimits {
    static let sourceBytes = 128 * 1024 * 1024
    static let projectBytes = 384 * 1024 * 1024
    static let rasterPixels = 64_000_000
    static let previewPixels = 4096
}

struct BridgeRequest {
    let id: String
    let method: String
    let params: [String: Any]

    init(_ value: Any) throws {
        guard let object = value as? [String: Any], Set(object.keys) == ["id", "method", "params"],
              let id = object["id"] as? String, !id.isEmpty, id.count <= 128,
              let method = object["method"] as? String,
              let params = object["params"] as? [String: Any] else {
            throw NativeFailure("invalid_request", "Invalid native bridge request.")
        }
        self.id = id; self.method = method; self.params = params
    }

    func keys(_ required: Set<String>, optional: Set<String> = []) throws {
        let actual = Set(params.keys)
        guard required.isSubset(of: actual), actual.isSubset(of: required.union(optional)) else {
            throw NativeFailure("invalid_params", "Unexpected or missing parameters for \(method).")
        }
    }

    func string(_ key: String, maximum: Int) throws -> String {
        guard let result = params[key] as? String, result.utf8.count <= maximum else {
            throw NativeFailure("invalid_params", "Invalid \(key).")
        }
        return result
    }

    func integer(_ key: String, range: ClosedRange<Int>) throws -> Int {
        guard let number = params[key] as? NSNumber,
              CFGetTypeID(number) != CFBooleanGetTypeID(),
              number.doubleValue.isFinite, number.doubleValue.rounded() == number.doubleValue,
              range.contains(number.intValue) else {
            throw NativeFailure("invalid_params", "Invalid \(key).")
        }
        return number.intValue
    }

    func boolean(_ key: String) throws -> Bool {
        guard let number = params[key] as? NSNumber, CFGetTypeID(number) == CFBooleanGetTypeID() else {
            throw NativeFailure("invalid_params", "Invalid \(key).")
        }
        return number.boolValue
    }
}

func decodeBase64(_ value: String, maximum: Int) throws -> Data {
    guard value.utf8.count <= (maximum + 2) / 3 * 4,
          let result = Data(base64Encoded: value), !result.isEmpty, result.count <= maximum else {
        throw NativeFailure("invalid_bytes", "File bytes are invalid or exceed the supported size.")
    }
    return result
}

func safeFilename(_ value: String, extension suffix: String) -> String {
    let leaf = URL(fileURLWithPath: value).lastPathComponent
    let stem = (leaf as NSString).deletingPathExtension
    let safe = stem.filter { !$0.isNewline && !$0.isASCIIControl }
    return String((safe.isEmpty ? "Figure Assembly" : safe).prefix(160)) + "." + suffix
}

private extension Character {
    var isASCIIControl: Bool { unicodeScalars.contains { $0.value < 32 || $0.value == 127 } }
}
