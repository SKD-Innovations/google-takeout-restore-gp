import Foundation
import LocalAuthentication

// No app or Google password enters this process. macOS owns the authentication UI.
let context = LAContext()
var error: NSError?
guard context.canEvaluatePolicy(.deviceOwnerAuthentication, error: &error) else { exit(1) }
var finished = false
var accepted = false
context.evaluatePolicy(.deviceOwnerAuthentication,
    localizedReason: "Remove all local accounts, saved Google sessions and restore records on this Mac.") {
    success, _ in
    DispatchQueue.main.async {
        accepted = success
        finished = true
    }
}
let deadline = Date().addingTimeInterval(120)
while !finished && Date() < deadline {
    RunLoop.main.run(until: Date().addingTimeInterval(0.1))
}
context.invalidate()
exit(accepted ? 0 : 1)
