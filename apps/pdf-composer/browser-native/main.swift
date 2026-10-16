import AppKit
import Foundation

do {
    let context = try LauncherContext()
    let arguments = Array(CommandLine.arguments.dropFirst())
    if arguments == ["--status"] || arguments == ["--stop"] {
        exit(runControlCommand(arguments[0], context: context))
    }
    guard arguments.isEmpty else { throw LauncherFailure(message: "支持 --status 或 --stop；普通使用请双击应用。") }
    let application = NSApplication.shared
    application.setActivationPolicy(.regular)
    let delegate = BrowserLauncher(context: context)
    application.delegate = delegate
    application.run()
    withExtendedLifetime(delegate) {}
} catch {
    fputs("Figure Assembly Browser: \(error.localizedDescription)\n", stderr)
    let app = NSApplication.shared; app.setActivationPolicy(.regular)
    let alert = NSAlert(); alert.messageText = "Figure Assembly Browser 启动失败"
    alert.informativeText = error.localizedDescription
    alert.addButton(withTitle: "退出")
    app.activate(ignoringOtherApps: true); alert.runModal()
    exit(1)
}
