import CryptoKit
import Darwin
import Foundation

struct FileSnapshot: Equatable {
    let device: UInt64
    let inode: UInt64
    let hash: String
}

/// Content tokens live only in this app session. They never enter portable project JSON.
final class ProjectFiles {
    private struct Session { let url: URL; var snapshot: FileSnapshot }
    private var sessions: [String: Session] = [:]

    func open(_ url: URL) throws -> [String: Any] {
        let (bytes, snapshot) = try Self.read(url, maximum: NativeLimits.projectBytes)
        guard let text = String(data: bytes, encoding: .utf8) else {
            throw NativeFailure("invalid_project", "This project is not UTF-8 JSON.")
        }
        let token = UUID().uuidString
        sessions[token] = Session(url: url, snapshot: snapshot)
        return ["name": url.lastPathComponent, "text": text, "token": token]
    }

    func url(for token: String) throws -> URL {
        guard let session = sessions[token] else {
            throw NativeFailure("unknown_save_token", "Reopen the project or use Save As to choose a file.")
        }
        return session.url
    }

    func save(_ text: String, token: String?, destination: URL?) throws -> [String: Any] {
        let bytes = Data(text.utf8)
        guard !bytes.isEmpty, bytes.count <= NativeLimits.projectBytes else {
            throw NativeFailure("project_too_large", "The project exceeds the supported file size.")
        }
        let url: URL
        let expected: FileSnapshot?
        if let token {
            guard let session = sessions[token] else {
                throw NativeFailure("unknown_save_token", "Reopen the project or use Save As to choose a file.")
            }
            url = session.url; expected = session.snapshot
        } else if let destination {
            url = destination
            expected = try Self.existingSnapshot(destination)
        } else {
            throw NativeFailure("missing_destination", "Choose a project destination.")
        }
        try Self.replace(bytes, at: url, expected: expected)
        let (_, current) = try Self.read(url, maximum: NativeLimits.projectBytes)
        let updatedToken = token ?? UUID().uuidString
        sessions[updatedToken] = Session(url: url, snapshot: current)
        return ["cancelled": false, "name": url.lastPathComponent, "token": updatedToken]
    }

    static func existingSnapshot(_ url: URL) throws -> FileSnapshot? {
        var info = stat()
        if lstat(url.path, &info) != 0 {
            if errno == ENOENT { return nil }
            throw NativeFailure("file_read", "Cannot inspect the selected file.")
        }
        return try read(url, maximum: NativeLimits.projectBytes).1
    }

    static func read(_ url: URL, maximum: Int) throws -> (Data, FileSnapshot) {
        let descriptor = Darwin.open(url.path, O_RDONLY | O_NOFOLLOW)
        guard descriptor >= 0 else {
            throw NativeFailure("file_read", "Cannot read this file. Symbolic links are not supported.")
        }
        defer { close(descriptor) }
        var info = stat()
        guard fstat(descriptor, &info) == 0, (info.st_mode & S_IFMT) == S_IFREG,
              info.st_size >= 0, info.st_size <= maximum else {
            throw NativeFailure("file_read", "Choose a regular file within the supported size.")
        }
        let handle = FileHandle(fileDescriptor: descriptor, closeOnDealloc: false)
        let bytes = try handle.readToEnd() ?? Data()
        var after = stat()
        guard bytes.count <= maximum, fstat(descriptor, &after) == 0,
              info.st_size == after.st_size, info.st_mtimespec.tv_sec == after.st_mtimespec.tv_sec,
              info.st_mtimespec.tv_nsec == after.st_mtimespec.tv_nsec else {
            throw NativeFailure("file_changed", "The file changed while it was being read. Try again.")
        }
        let digest = SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined()
        return (bytes, FileSnapshot(device: UInt64(info.st_dev), inode: UInt64(info.st_ino), hash: digest))
    }

    /// Coordinates cooperating writers, verifies the exact content token, then atomically renames.
    static func replace(_ bytes: Data, at url: URL, expected: FileSnapshot?) throws {
        let coordinator = NSFileCoordinator()
        var coordinationError: NSError?
        var result: Result<Void, Error>?
        coordinator.coordinate(writingItemAt: url, options: .forReplacing, error: &coordinationError) { target in
            result = Result { try replaceCoordinated(bytes, at: target, expected: expected) }
        }
        if let coordinationError { throw coordinationError }
        guard let result else { throw NativeFailure("file_write", "The file could not be coordinated for saving.") }
        try result.get()
    }

    private static func replaceCoordinated(_ bytes: Data, at url: URL, expected: FileSnapshot?) throws {
        guard try existingSnapshot(url) == expected else {
            throw NativeFailure("save_conflict", "This file changed outside Figure Assembly. Use Save As to keep both versions.")
        }
        let directory = url.deletingLastPathComponent()
        let temporary = directory.appendingPathComponent(".figure-assembly-\(UUID().uuidString).tmp")
        let descriptor = Darwin.open(temporary.path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, S_IRUSR | S_IWUSR)
        guard descriptor >= 0 else { throw NativeFailure("file_write", "Cannot create a temporary file beside the destination.") }
        var closed = false
        defer { if !closed { close(descriptor) }; try? FileManager.default.removeItem(at: temporary) }
        try bytes.withUnsafeBytes { buffer in
            var offset = 0
            while offset < buffer.count {
                let count = Darwin.write(descriptor, buffer.baseAddress!.advanced(by: offset), buffer.count - offset)
                if count < 0 && errno == EINTR { continue }
                guard count > 0 else { throw NativeFailure("file_write", "Writing the destination failed.") }
                offset += count
            }
        }
        guard fsync(descriptor) == 0 else { throw NativeFailure("file_write", "Could not flush the saved file.") }
        close(descriptor); closed = true
        guard try existingSnapshot(url) == expected else {
            throw NativeFailure("save_conflict", "This file changed during saving. Use Save As to keep both versions.")
        }
        guard rename(temporary.path, url.path) == 0 else { throw NativeFailure("file_write", "Could not install the saved file.") }
        let parent = Darwin.open(directory.path, O_RDONLY)
        if parent >= 0 { _ = fsync(parent); close(parent) }
    }
}
