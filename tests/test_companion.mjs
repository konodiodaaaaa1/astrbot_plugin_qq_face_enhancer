import assert from "node:assert/strict";
import test from "node:test";

import {
  buildRainbowDragonPacket,
  decodeProtoFields,
  parseSendMessageResponse
} from "../napcat_companion/napcat-plugin-qq-face-enhancer/index.mjs";

function bytesField(fields, tag, index = 0) {
  return fields.filter((field) => field.tag === tag && field.wireType === 2)[index]?.value;
}

function varintField(fields, tag) {
  return fields.find((field) => field.tag === tag && field.wireType === 0)?.value;
}

function rainbowFields(packet) {
  const outer = decodeProtoFields(packet);
  const body = decodeProtoFields(bytesField(outer, 3));
  const richText = decodeProtoFields(bytesField(body, 1));
  const faceElement = decodeProtoFields(bytesField(richText, 2, 0));
  const common = decodeProtoFields(bytesField(faceElement, 53));
  return decodeProtoFields(bytesField(common, 2));
}

test("builds private rainbow dragon packet with the verified overflow sticker type", () => {
  const packet = buildRainbowDragonPacket({
    peerType: "private",
    peerId: "2452585759",
    peerUid: "u_NriMlGKndiASGXWn5WIQqA",
    messageSequence: 4130,
    messageRandom: 1168743020,
    timestamp: 1787304449
  });
  const outer = decodeProtoFields(packet);
  const routing = decodeProtoFields(bytesField(outer, 1));
  const c2c = decodeProtoFields(bytesField(routing, 1));
  assert.equal(bytesField(c2c, 2).toString(), "u_NriMlGKndiASGXWn5WIQqA");

  const face = rainbowFields(packet);
  assert.equal(bytesField(face, 1).toString(), "1");
  assert.equal(bytesField(face, 2).toString(), "40");
  assert.equal(varintField(face, 3), 394n);
  assert.equal(varintField(face, 5), 4294967299n);
  assert.equal(bytesField(face, 6).toString(), "1");
  assert.equal(bytesField(face, 8).toString(), "100");
  assert.equal(face.some((field) => field.tag === 4 || field.tag === 9), false);
  assert.equal(
    packet.toString("hex"),
    "0a1c0a1a1218755f4e72694d6c474b6e646941534758576e355749517141" +
      "12060801100018001a83010a80011230aa032d082512270a013112023430" +
      "188a032883808080103201313a0d2fe696b0e5b9b4e5a4a7e9be994203" +
      "3130301801124c0a4a0a0d2fe696b0e5b9b4e5a4a7e9be9962390a375b" +
      "e696b0e5b9b4e5a4a7e9be995de8afb7e4bdbfe794a8e69c80e696b0e7" +
      "8988e6898be69cba5151e4bd93e9aa8ce696b0e58a9fe883bd20a22028" +
      "ecb4a6ad0432060881b4a0d406"
  );
});

test("builds the same effect for a group routing head", () => {
  const packet = buildRainbowDragonPacket({
    peerType: "group",
    peerId: "123456789",
    messageSequence: 5000,
    messageRandom: 6000,
    timestamp: 1787304449
  });
  const outer = decodeProtoFields(packet);
  const routing = decodeProtoFields(bytesField(outer, 1));
  const group = decodeProtoFields(bytesField(routing, 2));
  assert.equal(varintField(group, 1), 123456789n);
  assert.equal(varintField(rainbowFields(packet), 5), 4294967299n);
});

test("parses the successful QQ response captured during verification", () => {
  const response = Buffer.from("08001881b4a0d40650006081b4a0d40670d04c", "hex");
  assert.deepEqual(parseSendMessageResponse(response), {
    result: 0,
    sendTime: "1787304449",
    messageSequence: "9808"
  });
});
