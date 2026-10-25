// Draws the launcher icon (1024x1024 PNG) in the FBC brand: black tile, cyan "porch light" glow,
// "CC" in Lato Black and two caption bars. Used by tools/make_launcher.sh.
//   swift tools/launcher_icon.swift <out.png> <Lato-Black.ttf>
import AppKit
import CoreText

let args = CommandLine.arguments
let out = URL(fileURLWithPath: args[1])
CTFontManagerRegisterFontsForURL(URL(fileURLWithPath: args[2]) as CFURL, .process, nil)

let size = 1024.0
let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(size), pixelsHigh: Int(size), bitsPerSample: 8,
                           samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB,
                           bytesPerRow: 0, bitsPerPixel: 0)!
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)

let cyan = NSColor(srgbRed: 0x02 / 255, green: 0xCA / 255, blue: 0xF2 / 255, alpha: 1)
let tile = NSRect(x: 100, y: 100, width: 824, height: 824)            // macOS icon grid
let shape = NSBezierPath(roundedRect: tile, xRadius: 185, yRadius: 185)
NSColor.black.setFill()
shape.fill()

// Porch-light glow from the top-left corner.
shape.addClip()
let glow = NSGradient(colors: [cyan.withAlphaComponent(0.55), cyan.withAlphaComponent(0.0)])!
glow.draw(fromCenter: NSPoint(x: 160, y: 880), radius: 0, toCenter: NSPoint(x: 160, y: 880), radius: 620, options: [])

// "CC"
let font = NSFont(name: "Lato-Black", size: 360) ?? NSFont.boldSystemFont(ofSize: 360)
let text = NSAttributedString(string: "CC", attributes: [.font: font, .foregroundColor: NSColor.white, .kern: -6])
let ts = text.size()
text.draw(at: NSPoint(x: (size - ts.width) / 2, y: 470))

// Two caption bars underneath.
NSColor(srgbRed: 0xD0 / 255, green: 0xD4 / 255, blue: 0xD7 / 255, alpha: 1).setFill()
NSBezierPath(roundedRect: NSRect(x: 230, y: 330, width: 564, height: 64), xRadius: 32, yRadius: 32).fill()
cyan.setFill()
NSBezierPath(roundedRect: NSRect(x: 230, y: 220, width: 380, height: 64), xRadius: 32, yRadius: 32).fill()

NSGraphicsContext.restoreGraphicsState()
try! rep.representation(using: .png, properties: [:])!.write(to: out)
