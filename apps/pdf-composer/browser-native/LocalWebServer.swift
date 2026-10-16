import Darwin
import Foundation
import Network

struct BrowserBuild: Codable, Sendable, Equatable {
    let applicationID: String
    let sourceHead: String
    let contentHash: String
}

struct BrowserHealth: Codable, Sendable, Equatable {
    let applicationID: String
    let sourceHead: String
    let contentHash: String
    let instanceID: String
    let pid: Int32
    let port: UInt16
}

private enum LocalWebServerError: LocalizedError {
    case stopped, invalidConfiguration, startupTimedOut, invalidFile, fileTooLarge

    var errorDescription: String? {
        switch self {
        case .stopped: "The local browser server has stopped."
        case .invalidConfiguration: "The local browser server configuration is invalid."
        case .startupTimedOut: "The local browser server did not become ready in time."
        case .invalidFile: "The requested bundled resource is unavailable."
        case .fileTooLarge: "The requested bundled resource exceeds the local server limit."
        }
    }
}

private struct BrowserHTTPRequest {
    let method: String
    let target: String
    let headers: [String: String]

    init?(_ bytes: Data) {
        guard let text = String(data: bytes, encoding: .ascii) else { return nil }
        let lines = text.components(separatedBy: "\r\n")
        guard let first = lines.first, lines.count <= 256 else { return nil }
        let request = first.split(separator: " ", omittingEmptySubsequences: false)
        guard request.count == 3, request[2] == "HTTP/1.1" || request[2] == "HTTP/1.0",
              !request[0].isEmpty, !request[1].isEmpty else { return nil }
        var headers: [String: String] = [:]
        let token = CharacterSet(charactersIn: "!#$%&'*+-.^_`|~0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
        for line in lines.dropFirst() {
            guard let colon = line.firstIndex(of: ":") else { return nil }
            let name = String(line[..<colon])
            guard !name.isEmpty, name.unicodeScalars.allSatisfy({ token.contains($0) }) else { return nil }
            let value = String(line[line.index(after: colon)...]).trimmingCharacters(in: .whitespaces)
            guard value.unicodeScalars.allSatisfy({ $0.value == 9 || ($0.value >= 32 && $0.value < 127) }) else { return nil }
            let key = name.lowercased()
            guard headers[key] == nil else { return nil }
            headers[key] = value
        }
        self.method = String(request[0])
        self.target = String(request[1])
        self.headers = headers
    }
}

// NW callbacks, descriptors and mutable connection state are confined to queue.
final class LocalWebServer: @unchecked Sendable {
    private final class Client: @unchecked Sendable {
        let id = UUID()
        let connection: NWConnection
        var header = Data()
        var deadline: DispatchWorkItem?
        var responding = false
        var headOnly = false
        init(_ connection: NWConnection) { self.connection = connection }
    }

    private let root: URL
    private let build: BrowserBuild
    private let instanceID: String
    private let requestedPort: UInt16
    private let allowedFiles: Set<String>
    private let logger: @Sendable (String) -> Void
    private let queue = DispatchQueue(label: "figure-assembly.local-http")
    private var listener: NWListener?
    private var clients: [UUID: Client] = [:]
    private var rootDescriptor: Int32 = -1
    private var health: BrowserHealth?
    private var stopped = false
    private var startupDeadline: DispatchWorkItem?
    private var startReplies: [@Sendable (Result<BrowserHealth, Error>) -> Void] = []
    private static let headerLimit = 16 * 1024
    private static let fileLimit = 64 * 1024 * 1024
    private static let endOfHeader = Data("\r\n\r\n".utf8)

    init(root: URL, build: BrowserBuild, instanceID: String, port: UInt16,
         allowedFiles: Set<String>, logger: @escaping @Sendable (String) -> Void) {
        self.root = root.standardizedFileURL.resolvingSymlinksInPath()
        self.build = build
        self.instanceID = instanceID
        self.requestedPort = port
        self.allowedFiles = allowedFiles
        self.logger = logger
    }

    func start(completion: @escaping @Sendable (Result<BrowserHealth, Error>) -> Void) {
        queue.async { [self] in
            if stopped { completion(.failure(LocalWebServerError.stopped)); return }
            if let health { completion(.success(health)); return }
            startReplies.append(completion)
            if listener != nil { return }
            guard root.isFileURL, allowedFiles.contains("index.html"),
                  allowedFiles.allSatisfy(Self.safeRelativePath),
                  [build.applicationID, build.sourceHead, build.contentHash, instanceID].allSatisfy({ !$0.isEmpty && $0.utf8.count <= 1024 }) else {
                failStart(LocalWebServerError.invalidConfiguration); return
            }
            rootDescriptor = root.withUnsafeFileSystemRepresentation { path in
                guard let path else { return -1 }
                return Darwin.open(path, O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW)
            }
            guard rootDescriptor >= 0 else { failStart(Self.posixError()); return }
            let parameters = NWParameters.tcp
            parameters.allowLocalEndpointReuse = false
            parameters.requiredLocalEndpoint = .hostPort(host: .ipv4(IPv4Address("127.0.0.1")!),
                                                         port: NWEndpoint.Port(rawValue: requestedPort)!)
            do {
                let listener = try NWListener(using: parameters)
                self.listener = listener
                listener.newConnectionHandler = { [weak self] connection in
                    guard let self else { connection.cancel(); return }
                    self.accept(connection)
                }
                listener.stateUpdateHandler = { [weak self] state in self?.listenerChanged(state) }
                let deadline = DispatchWorkItem { [weak self] in self?.failStart(LocalWebServerError.startupTimedOut) }
                startupDeadline = deadline
                queue.asyncAfter(deadline: .now() + 5, execute: deadline)
                listener.start(queue: queue)
            } catch { failStart(error) }
        }
    }

    func stop() { queue.async { [self] in stopOnQueue() } }

    deinit {
        startupDeadline?.cancel()
        listener?.cancel()
        for client in clients.values { client.deadline?.cancel(); client.connection.cancel() }
        if rootDescriptor >= 0 { Darwin.close(rootDescriptor) }
    }

    private func listenerChanged(_ state: NWListener.State) {
        switch state {
        case .ready:
            guard !stopped, let port = listener?.port?.rawValue, port != 0 else {
                failStart(LocalWebServerError.invalidConfiguration); return
            }
            let ready = BrowserHealth(applicationID: build.applicationID, sourceHead: build.sourceHead,
                                      contentHash: build.contentHash, instanceID: instanceID, pid: getpid(), port: port)
            health = ready
            startupDeadline?.cancel(); startupDeadline = nil
            logger("server_listening address=127.0.0.1 port=\(port) pid=\(ready.pid) instance=\(instanceID)")
            let replies = startReplies; startReplies.removeAll()
            for reply in replies { reply(.success(ready)) }
        case .failed(let error): failStart(error)
        case .cancelled:
            if !stopped { failStart(LocalWebServerError.stopped) }
        default: break
        }
    }

    private func failStart(_ error: Error) {
        let replies = startReplies; startReplies.removeAll()
        logger("server_failed reason=\(error.localizedDescription)")
        stopOnQueue()
        for reply in replies { reply(.failure(error)) }
    }

    private func stopOnQueue() {
        if stopped { return }
        stopped = true
        startupDeadline?.cancel(); startupDeadline = nil
        listener?.stateUpdateHandler = nil; listener?.newConnectionHandler = nil
        listener?.cancel(); listener = nil
        for client in clients.values {
            client.deadline?.cancel(); client.connection.stateUpdateHandler = nil; client.connection.cancel()
        }
        clients.removeAll(); health = nil
        if rootDescriptor >= 0 { Darwin.close(rootDescriptor); rootDescriptor = -1 }
        let replies = startReplies; startReplies.removeAll()
        for reply in replies { reply(.failure(LocalWebServerError.stopped)) }
        logger("server_stopped instance=\(instanceID)")
    }

    private func accept(_ connection: NWConnection) {
        guard !stopped, health != nil, clients.count < 16 else { connection.cancel(); return }
        let client = Client(connection)
        clients[client.id] = client
        let deadline = DispatchWorkItem { [weak self, weak client] in
            guard let self, let client else { return }
            self.logger("request_timeout")
            self.close(client)
        }
        client.deadline = deadline
        queue.asyncAfter(deadline: .now() + 5, execute: deadline)
        connection.stateUpdateHandler = { [weak self, weak client] state in
            guard let self, let client else { return }
            if case .failed = state { self.close(client) }
            if case .cancelled = state { self.close(client) }
        }
        connection.start(queue: queue)
        receive(client)
    }

    private func receive(_ client: Client) {
        client.connection.receive(minimumIncompleteLength: 1, maximumLength: 4096) { [weak self, weak client] data, _, complete, error in
            guard let self, let client, self.clients[client.id] != nil, !client.responding else { return }
            if let data { client.header.append(data) }
            if let boundary = client.header.range(of: Self.endOfHeader) {
                guard boundary.upperBound <= Self.headerLimit else { self.refuse(client, 431); return }
                guard boundary.upperBound == client.header.count,
                      let request = BrowserHTTPRequest(client.header.subdata(in: 0..<boundary.lowerBound)) else {
                    self.refuse(client, 400); return
                }
                self.respond(client, to: request)
            } else if client.header.count >= Self.headerLimit { self.refuse(client, 431) }
            else if error != nil || complete { self.close(client) }
            else { self.receive(client) }
        }
    }

    private func respond(_ client: Client, to request: BrowserHTTPRequest) {
        client.headOnly = request.method == "HEAD"
        guard let health else { close(client); return }
        guard request.method == "GET" || request.method == "HEAD" else { refuse(client, 405); return }
        guard request.headers["host"] == "127.0.0.1:\(health.port)" || (health.port == 80 && request.headers["host"] == "127.0.0.1"),
              request.headers["transfer-encoding"] == nil, request.headers["expect"] == nil,
              request.headers["content-length"] == nil || request.headers["content-length"] == "0" else { refuse(client, 400); return }
        guard request.target.utf8.count <= 8192, !request.target.contains("#"),
              let decoded = request.target.split(separator: "?", maxSplits: 1, omittingEmptySubsequences: false).first.map(String.init)?.removingPercentEncoding,
              decoded.hasPrefix("/"), !decoded.hasPrefix("//") else { refuse(client, 400); return }
        if decoded == "/__figure_assembly_health" {
            guard request.method == "GET" else { refuse(client, 405); return }
            guard let body = try? JSONEncoder().encode(health) else { refuse(client, 500); return }
            send(client, status: 200, type: "application/json; charset=utf-8", length: body.count, body: body)
            return
        }
        let relative = decoded == "/" ? "index.html" : String(decoded.dropFirst())
        guard Self.safeRelativePath(relative) else { refuse(client, 400); return }
        guard allowedFiles.contains(relative) else { refuse(client, 404); return }
        do {
            let asset = try readAsset(relative, headOnly: request.method == "HEAD")
            send(client, status: 200, type: Self.contentType(relative), length: asset.length, body: asset.body)
        } catch let error as POSIXError {
            refuse(client, error.code == .ENOENT || error.code == .ENOTDIR ? 404 : 403)
        } catch { refuse(client, 403) }
    }

    private func readAsset(_ relative: String, headOnly: Bool) throws -> (length: Int, body: Data?) {
        let components = relative.split(separator: "/").map(String.init)
        var directory = Darwin.dup(rootDescriptor)
        guard directory >= 0 else { throw Self.posixError() }
        defer { Darwin.close(directory) }
        for component in components.dropLast() {
            let next = component.withCString { Darwin.openat(directory, $0, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC) }
            guard next >= 0 else { throw Self.posixError() }
            Darwin.close(directory); directory = next
        }
        let file = components.last!.withCString { Darwin.openat(directory, $0, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC) }
        guard file >= 0 else { throw Self.posixError() }
        defer { Darwin.close(file) }
        var information = stat()
        guard Darwin.fstat(file, &information) == 0 else { throw Self.posixError() }
        guard information.st_mode & S_IFMT == S_IFREG, information.st_size >= 0 else { throw LocalWebServerError.invalidFile }
        guard information.st_size <= Self.fileLimit else { throw LocalWebServerError.fileTooLarge }
        if headOnly { return (Int(information.st_size), nil) }
        var body = Data(), buffer = [UInt8](repeating: 0, count: 32768)
        while true {
            let count = buffer.withUnsafeMutableBytes { Darwin.read(file, $0.baseAddress!, $0.count) }
            if count == 0 { break }
            if count < 0 { if errno == EINTR { continue }; throw Self.posixError() }
            guard body.count + count <= Self.fileLimit else { throw LocalWebServerError.fileTooLarge }
            body.append(contentsOf: buffer.prefix(count))
        }
        return (body.count, body)
    }

    private static func safeRelativePath(_ path: String) -> Bool {
        guard !path.isEmpty, !path.contains("\\"), !path.contains("%"), !path.contains("?"), !path.contains("#"),
              path.unicodeScalars.allSatisfy({ $0.value >= 32 && $0.value != 127 }) else { return false }
        return path.split(separator: "/", omittingEmptySubsequences: false).allSatisfy { !$0.isEmpty && $0 != "." && $0 != ".." }
    }

    private func refuse(_ client: Client, _ status: Int) {
        logger("request_refused status=\(status)")
        let body = Data("\(status) \(Self.reason(status))\n".utf8)
        send(client, status: status, type: "text/plain; charset=utf-8", length: body.count, body: body)
    }

    private func send(_ client: Client, status: Int, type: String, length: Int, body: Data?) {
        guard clients[client.id] != nil, !client.responding else { return }
        client.responding = true
        var bytes = Data("HTTP/1.1 \(status) \(Self.reason(status))\r\nContent-Type: \(type)\r\nContent-Length: \(length)\r\nCache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\nCross-Origin-Resource-Policy: same-origin\r\nConnection: close\r\n\r\n".utf8)
        if let body, !client.headOnly { bytes.append(body) }
        client.connection.send(content: bytes, contentContext: .finalMessage, isComplete: true, completion: .contentProcessed { [weak self, weak client] _ in
            guard let self, let client else { return }
            self.close(client)
        })
    }

    private func close(_ client: Client) {
        guard clients.removeValue(forKey: client.id) != nil else { return }
        client.deadline?.cancel(); client.deadline = nil
        client.connection.stateUpdateHandler = nil
        client.connection.cancel()
    }

    private static func posixError() -> POSIXError { POSIXError(POSIXErrorCode(rawValue: errno) ?? .EIO) }

    private static func reason(_ status: Int) -> String {
        switch status {
        case 200: "OK"
        case 400: "Bad Request"
        case 403: "Forbidden"
        case 404: "Not Found"
        case 405: "Method Not Allowed"
        case 431: "Request Header Fields Too Large"
        default: "Internal Server Error"
        }
    }

    private static func contentType(_ path: String) -> String {
        switch (path as NSString).pathExtension.lowercased() {
        case "html": "text/html; charset=utf-8"
        case "js", "mjs": "text/javascript; charset=utf-8"
        case "css": "text/css; charset=utf-8"
        case "json", "map": "application/json; charset=utf-8"
        case "svg": "image/svg+xml"
        case "png": "image/png"
        case "jpg", "jpeg": "image/jpeg"
        case "ico": "image/x-icon"
        case "woff": "font/woff"
        case "woff2": "font/woff2"
        case "ttf": "font/ttf"
        case "otf": "font/otf"
        case "wasm": "application/wasm"
        case "txt": "text/plain; charset=utf-8"
        default: "application/octet-stream"
        }
    }

    static func probeBrowserHealth(port: UInt16, timeout: TimeInterval,
                                   completion: @escaping @Sendable (BrowserHealth?) -> Void) {
        guard port != 0, timeout.isFinite, timeout > 0 else { completion(nil); return }
        BrowserHealthProbe(port: port, timeout: min(timeout, 30), completion: completion).start()
    }
}

// A bounded raw HTTP probe never follows redirects or consults proxy settings.
private final class BrowserHealthProbe: @unchecked Sendable {
    private let port: UInt16
    private let timeout: TimeInterval
    private let completion: @Sendable (BrowserHealth?) -> Void
    private let queue = DispatchQueue(label: "figure-assembly.health-probe")
    private let connection: NWConnection
    private var deadline: DispatchWorkItem?
    private var bytes = Data()
    private var finished = false

    init(port: UInt16, timeout: TimeInterval, completion: @escaping @Sendable (BrowserHealth?) -> Void) {
        self.port = port; self.timeout = timeout; self.completion = completion
        self.connection = NWConnection(host: .ipv4(IPv4Address("127.0.0.1")!),
                                       port: NWEndpoint.Port(rawValue: port)!, using: .tcp)
    }

    func start() {
        queue.async { [self] in
            let deadline = DispatchWorkItem { [self] in finish(nil) }
            self.deadline = deadline
            queue.asyncAfter(deadline: .now() + timeout, execute: deadline)
            connection.stateUpdateHandler = { [weak self] state in
                guard let self, !self.finished else { return }
                switch state {
                case .ready:
                    let request = Data("GET /__figure_assembly_health HTTP/1.1\r\nHost: 127.0.0.1:\(self.port)\r\nConnection: close\r\n\r\n".utf8)
                    self.connection.send(content: request, completion: .contentProcessed { [weak self] error in
                        guard let self else { return }
                        if error != nil { self.finish(nil) } else { self.receive() }
                    })
                case .failed, .waiting, .cancelled: self.finish(nil)
                default: break
                }
            }
            connection.start(queue: queue)
        }
    }

    private func receive() {
        connection.receive(minimumIncompleteLength: 1, maximumLength: 4096) { [weak self] data, _, complete, error in
            guard let self, !self.finished else { return }
            if let data { self.bytes.append(data) }
            guard self.bytes.count <= 32 * 1024 else { self.finish(nil); return }
            if let boundary = self.bytes.range(of: Data("\r\n\r\n".utf8)) {
                guard boundary.upperBound <= 16 * 1024,
                      let header = String(data: self.bytes.subdata(in: 0..<boundary.lowerBound), encoding: .ascii) else { self.finish(nil); return }
                let lines = header.components(separatedBy: "\r\n")
                guard lines.first == "HTTP/1.1 200 OK" || lines.first == "HTTP/1.0 200 OK" else { self.finish(nil); return }
                var fields: [String: String] = [:]
                for line in lines.dropFirst() {
                    guard let separator = line.firstIndex(of: ":") else { self.finish(nil); return }
                    let key = line[..<separator].lowercased()
                    guard fields[key] == nil else { self.finish(nil); return }
                    fields[key] = line[line.index(after: separator)...].trimmingCharacters(in: .whitespaces)
                }
                guard fields["transfer-encoding"] == nil, fields["location"] == nil,
                      fields["content-type"]?.lowercased().hasPrefix("application/json") == true,
                      let lengthText = fields["content-length"], let length = Int(lengthText), length >= 0, length <= 16 * 1024 else { self.finish(nil); return }
                let body = self.bytes.subdata(in: boundary.upperBound..<self.bytes.count)
                if body.count >= length {
                    guard body.count == length, let health = try? JSONDecoder().decode(BrowserHealth.self, from: body),
                          health.port == self.port, health.pid > 0,
                          [health.applicationID, health.sourceHead, health.contentHash, health.instanceID].allSatisfy({ !$0.isEmpty && $0.utf8.count <= 1024 }) else { self.finish(nil); return }
                    self.finish(health); return
                }
            } else if self.bytes.count >= 16 * 1024 { self.finish(nil); return }
            if error != nil || complete { self.finish(nil) } else { self.receive() }
        }
    }

    private func finish(_ health: BrowserHealth?) {
        guard !finished else { return }
        finished = true
        deadline?.cancel(); deadline = nil
        connection.stateUpdateHandler = nil; connection.cancel()
        completion(health)
    }
}
