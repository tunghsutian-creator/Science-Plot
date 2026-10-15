import AppKit

let application = NSApplication.shared
application.setActivationPolicy(.regular)
let delegate = AssemblyApplication()
application.delegate = delegate
application.run()
