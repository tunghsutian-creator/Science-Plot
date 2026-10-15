import assert from 'node:assert/strict';
import test from 'node:test';
import { deflateSync } from 'node:zlib';
import { toBase64 } from '../src/core/bytes';
import { inspectSource } from '../src/pdf';

// Generated2x3 RGB display fixture; no measurement data or external resources.
const jpeg = Uint8Array.from(atob('/9j/4AAQSkZJRgABAQEAlgCWAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAADAAIDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDkKKKKD78//9k='), (character) => character.charCodeAt(0));
function crc32(bytes: Uint8Array): number {
  let crc = 0xffffffff;
  for (const byte of bytes) { crc ^= byte; for (let bit = 0; bit < 8; bit++) crc = (crc >>> 1) ^ (crc & 1 ? 0xedb88320 : 0); }
  return (crc ^ 0xffffffff) >>> 0;
}
function chunk(type: string, data: Uint8Array): Uint8Array {
  const body = Buffer.concat([Buffer.from(type), data]), size = Buffer.alloc(4), crc = Buffer.alloc(4);
  size.writeUInt32BE(data.length); crc.writeUInt32BE(crc32(body)); return Buffer.concat([size, body, crc]);
}
function png(chunks: Uint8Array[] = []): Uint8Array {
  const header = Buffer.alloc(13); header.writeUInt32BE(1); header.writeUInt32BE(1, 4); header[8] = 8; header[9] = 2;
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', header), ...chunks,
    chunk('IDAT', deflateSync(Buffer.from([0, 180, 30, 80]))), chunk('IEND', new Uint8Array())]);
}
function number(value: number): Uint8Array { const out = Buffer.alloc(4); out.writeUInt32BE(value); return out; }
function jpegSegment(marker: number, payload: Uint8Array): Uint8Array {
  const prefix = Buffer.from([255, marker, 0, 0]); prefix.writeUInt16BE(payload.length + 2, 2);
  return Buffer.concat([jpeg.slice(0, 2), prefix, payload, jpeg.slice(2)]);
}
const srgb = chunk('sRGB', Uint8Array.of(0)), gamma = chunk('gAMA', number(45455));
const chromaticities = chunk('cHRM', Buffer.concat([31270, 32900, 64000, 33000, 30000, 60000, 15000, 6000].map(number)));

test('ordinary RGB JPEG keeps byte identity and source JFIF DPI outranks native guesses', async () => {
  const asset = await inspectSource({ name: 'display.jpg', bytesBase64: toBase64(jpeg), dpi: 300 });
  assert.equal(asset.kind, 'jpeg'); assert.equal(asset.pages[0].dpi, 150);
  assert.equal(asset.pages[0].pixelWidth, 2); assert.equal(asset.pages[0].pixelHeight, 3);
  assert.equal(asset.bytesBase64, toBase64(jpeg)); assert.equal(asset.pages[0].dpiAssumed, false);
});

test('JPEG ICC profile refuses rather than silently becoming unmanaged DeviceRGB', async () => {
  const profiled = jpegSegment(0xe2, Buffer.concat([Buffer.from('ICC_PROFILE\0'), Uint8Array.of(1, 1), Buffer.from('profile') ]));
  await assert.rejects(inspectSource({ name: 'profiled.jpg', bytesBase64: toBase64(profiled) }), /JPEG ICC color profiles are unsupported/);
});

test('JPEG EXIF rotation refuses rather than disagreeing with viewer orientation', async () => {
  const tiff = Buffer.alloc(26); tiff.write('II'); tiff.writeUInt16LE(42, 2); tiff.writeUInt32LE(8, 4); tiff.writeUInt16LE(1, 8);
  tiff.writeUInt16LE(274, 10); tiff.writeUInt16LE(3, 12); tiff.writeUInt32LE(1, 14); tiff.writeUInt16LE(6, 18);
  const rotated = jpegSegment(0xe1, Buffer.concat([Buffer.from('Exif\0\0'), tiff]));
  await assert.rejects(inspectSource({ name: 'rotated.jpg', bytesBase64: toBase64(rotated) }), /Rotated JPEG EXIF orientation/);
});

test('plain display PNG and explicitly canonical sRGB metadata remain supported', async () => {
  await inspectSource({ name: 'plain.png', bytesBase64: toBase64(png()) });
  await inspectSource({ name: 'srgb.png', bytesBase64: toBase64(png([srgb, gamma, chromaticities])) });
});

for (const [name, chunks, message] of [
  ['ICC', [chunk('iCCP', Buffer.from('custom\0\0compressed-profile'))], /PNG ICC color profiles/],
  ['linear gamma', [srgb, chunk('gAMA', number(100000))], /Nonstandard PNG gamma/],
  ['custom chromaticities', [srgb, chunk('cHRM', Buffer.alloc(32))], /Nonstandard PNG chromaticities/],
  ['unproven transfer', [gamma], /explicit standard sRGB declaration/],
] as const) {
  test(`PNG ${name} refuses without discarding color interpretation`, async () => {
    await assert.rejects(inspectSource({ name: `${name}.png`, bytesBase64: toBase64(png([...chunks])) }), message);
  });
}
