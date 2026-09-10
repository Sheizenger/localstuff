// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "Horizon",
    platforms: [
        .macOS(.v13),
        .iOS(.v16)
    ],
    targets: [
        .target(
            name: "HorizonCore",
            path: "Sources/HorizonCore"
        ),
        .target(
            name: "HorizonUI",
            dependencies: ["HorizonCore"],
            path: "Sources/HorizonUI"
        ),
        .executableTarget(
            name: "Horizon",
            dependencies: ["HorizonCore", "HorizonUI"],
            path: "Sources/Horizon"
        ),
        .executableTarget(
            name: "HorizonMobile",
            dependencies: ["HorizonCore", "HorizonUI"],
            path: "Sources/HorizonMobile"
        )
    ]
)
