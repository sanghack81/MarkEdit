import Foundation
setbuf(stdout,nil)
precondition(CommandLine.arguments.count == 2)
let file = URL(fileURLWithPath:CommandLine.arguments[1])
let coordinator = NSFileCoordinator(filePresenter:nil)
var error:NSError?
Swift.print("WRITE_REQUEST",Date().timeIntervalSince1970)
coordinator.coordinate(writingItemAt:file, options:.forMerging, error:&error) { url in
  Swift.print("WRITE_GRANTED",Date().timeIntervalSince1970)
  do {
    try Data("# External fixture update\n\nWritten by the isolated coordinator.\n".utf8).write(to:url)
    Swift.print("WRITE_DONE")
  } catch {
    fputs("WRITE_ERROR \(error)\n",stderr)
    exit(3)
  }
}
Swift.print("COORDINATOR_RETURNED",String(describing:error))
exit(error == nil ? 0 : 2)
