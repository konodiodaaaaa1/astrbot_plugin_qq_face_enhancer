import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";

const ELEMENT_TEXT = 1;
const ELEMENT_FACE = 6;
const CHAT_PRIVATE = 1;
const CHAT_GROUP = 2;
const FACE_NORMAL = 2;
const FACE_ANIMATED = 3;
const SPECIAL_RAINBOW_DRAGON = "rainbow_dragon_2024";
const SEND_MESSAGE_COMMAND = "MessageSvc.PbSendMsg";

let pluginConfig = { token: "" };
let logger;
const clientSequences = new Map();

function loadConfig(ctx) {
  try {
    if (fs.existsSync(ctx.configPath)) {
      pluginConfig = { ...pluginConfig, ...JSON.parse(fs.readFileSync(ctx.configPath, "utf8")) };
    }
  } catch (error) {
    logger?.warn("Failed to load config", error);
  }
}

function unauthorized(req, res) {
  const expected = String(pluginConfig.token || "");
  if (!expected) {
    res.status(503).json({ code: -1, message: "configure companion token before enabling native sending" });
    return true;
  }
  const actual = String(req.headers?.["x-qqface-token"] || req.body?.token || "");
  if (actual === expected) return false;
  res.status(401).json({ code: -1, message: "invalid token" });
  return true;
}

function positiveId(value, field) {
  const text = String(value ?? "").trim();
  if (!/^\d+$/.test(text) || text === "0") throw new Error(`${field} must be a positive numeric string`);
  return text;
}

function optionalText(value, field, max = 128) {
  const text = String(value ?? "");
  if (text.length > max || [...text].some((char) => char.charCodeAt(0) < 32)) {
    throw new Error(`${field} is invalid`);
  }
  return text;
}

function encodeVarint(value) {
  let current = BigInt(value);
  if (current < 0n) throw new Error("protobuf varint must be non-negative");
  const bytes = [];
  do {
    let byte = Number(current & 0x7fn);
    current >>= 7n;
    if (current) byte |= 0x80;
    bytes.push(byte);
  } while (current);
  return Buffer.from(bytes);
}

function fieldVarint(tag, value) {
  return Buffer.concat([encodeVarint(BigInt(tag) << 3n), encodeVarint(value)]);
}

function fieldBytes(tag, value) {
  const data = Buffer.isBuffer(value) ? value : Buffer.from(String(value), "utf8");
  return Buffer.concat([
    encodeVarint((BigInt(tag) << 3n) | 2n),
    encodeVarint(data.length),
    data
  ]);
}

function concatFields(...fields) {
  return Buffer.concat(fields.filter(Boolean));
}

function randomPositiveInt32() {
  return (crypto.randomBytes(4).readUInt32BE(0) & 0x7fffffff) || 1;
}

async function nextClientSequence(ctx, peer) {
  const key = `${peer.chatType}:${peer.peerUid}`;
  let observed = 0;
  try {
    const latest = await ctx.core.apis.MsgApi.getAioFirstViewLatestMsgs(peer, 50);
    observed = Math.max(
      0,
      ...((latest?.msgList || []).map((message) => Number(message?.clientSeq || 0))
        .filter((value) => Number.isSafeInteger(value) && value > 0))
    );
  } catch (error) {
    logger?.warn("Failed to read latest client sequence", error);
  }
  const next = Math.max(observed, clientSequences.get(key) || 0) + 1;
  clientSequences.set(key, next);
  return next;
}

export function decodeProtoFields(input) {
  const data = Buffer.from(input || []);
  let offset = 0;
  const fields = [];
  const readVarint = () => {
    let value = 0n;
    let shift = 0n;
    while (offset < data.length) {
      const byte = data[offset++];
      value |= BigInt(byte & 0x7f) << shift;
      if ((byte & 0x80) === 0) return value;
      shift += 7n;
      if (shift > 70n) throw new Error("protobuf varint is too long");
    }
    throw new Error("truncated protobuf varint");
  };
  while (offset < data.length) {
    const key = readVarint();
    const tag = Number(key >> 3n);
    const wireType = Number(key & 7n);
    if (wireType === 0) {
      fields.push({ tag, wireType, value: readVarint() });
      continue;
    }
    if (wireType === 2) {
      const length = Number(readVarint());
      const value = data.subarray(offset, offset + length);
      if (value.length !== length) throw new Error("truncated protobuf bytes field");
      offset += length;
      fields.push({ tag, wireType, value });
      continue;
    }
    throw new Error(`unsupported protobuf wire type ${wireType}`);
  }
  return fields;
}

function firstVarint(fields, tag, fallback = 0n) {
  return fields.find((field) => field.tag === tag && field.wireType === 0)?.value ?? fallback;
}

export function buildRainbowDragonPacket({
  peerType,
  peerId,
  peerUid = "",
  messageSequence,
  messageRandom,
  timestamp
}) {
  let route;
  if (peerType === "private") {
    if (!peerUid) throw new Error("peerUid is required for private rainbow dragon sending");
    route = fieldBytes(1, fieldBytes(2, peerUid));
  } else if (peerType === "group") {
    route = fieldBytes(2, fieldVarint(1, BigInt(positiveId(peerId, "group_id"))));
  } else {
    throw new Error("peer.type must be private or group");
  }

  const bigFace = concatFields(
    fieldBytes(1, "1"),
    fieldBytes(2, "40"),
    fieldVarint(3, 394),
    fieldVarint(5, 4294967299n),
    fieldBytes(6, "1"),
    fieldBytes(7, "/新年大龙"),
    fieldBytes(8, "100")
  );
  const common = concatFields(
    fieldVarint(1, 37),
    fieldBytes(2, bigFace),
    fieldVarint(3, 1)
  );
  const faceElement = fieldBytes(53, common);
  const fallbackText = concatFields(
    fieldBytes(1, "/新年大龙"),
    fieldBytes(12, fieldBytes(1, "[新年大龙]请使用最新版手机QQ体验新功能"))
  );
  const textElement = fieldBytes(1, fallbackText);
  const richText = concatFields(fieldBytes(2, faceElement), fieldBytes(2, textElement));
  const body = fieldBytes(1, richText);
  const contentHead = concatFields(
    fieldVarint(1, 1),
    fieldVarint(2, 0),
    fieldVarint(3, 0)
  );
  const syncCookie = fieldVarint(1, timestamp);
  return concatFields(
    fieldBytes(1, route),
    fieldBytes(2, contentHead),
    fieldBytes(3, body),
    fieldVarint(4, messageSequence),
    fieldVarint(5, messageRandom),
    fieldBytes(6, syncCookie)
  );
}

export function parseSendMessageResponse(input) {
  const fields = decodeProtoFields(input);
  return {
    result: Number(firstVarint(fields, 1)),
    sendTime: firstVarint(fields, 3).toString(),
    messageSequence: firstVarint(fields, 14).toString()
  };
}

async function makePeer(ctx, body) {
  const peer = body?.peer || {};
  const type = String(peer.type || body?.message_type || "").toLowerCase();
  const id = peer.id ?? (type === "group" ? body?.group_id : body?.user_id);
  if (type === "group") {
    return {
      chatType: CHAT_GROUP,
      peerUid: positiveId(id, "group_id")
    };
  }

  const userId = positiveId(id, "user_id");
  const peerUid = await ctx.core?.apis?.UserApi?.getUidByUinV2(userId);
  if (!peerUid) {
    throw new Error(`cannot resolve private user_id ${userId} to QQNT uid`);
  }
  return {
    chatType: CHAT_PRIVATE,
    peerUid: String(peerUid),
    guildId: ""
  };
}

function makeTextElement(text) {
  return {
    elementType: ELEMENT_TEXT,
    elementId: "",
    textElement: {
      content: text,
      atType: 0,
      atUid: "",
      atTinyId: "",
      atNtUid: ""
    }
  };
}

function makeFaceElement(body) {
  const face = body?.face || body || {};
  const faceId = positiveId(face.face_id ?? face.id, "face_id");
  const stickerType = Number(face.sticker_type ?? face.stickerType ?? 0) || 0;
  const faceType = Number(face.face_type ?? face.faceType ?? (stickerType ? FACE_ANIMATED : FACE_NORMAL));
  if (![1, FACE_NORMAL, FACE_ANIMATED, 4].includes(faceType)) throw new Error("face_type is invalid");
  const element = {
    elementType: ELEMENT_FACE,
    elementId: "",
    faceElement: {
      faceIndex: Number(faceId),
      faceType,
      faceText: optionalText(face.face_text ?? face.faceText ?? "", "face_text", 256),
      packId: optionalText(face.pack_id ?? face.packId ?? "", "pack_id"),
      stickerId: optionalText(face.sticker_id ?? face.stickerId ?? "", "sticker_id"),
      sourceType: Number(face.source_type ?? face.sourceType ?? 1),
      stickerType,
      resultId: optionalText(face.result_id ?? face.resultId ?? "", "result_id"),
      surpriseId: optionalText(face.surprise_id ?? face.surpriseId ?? "", "surprise_id"),
      randomType: Number(face.random_type ?? face.randomType ?? 0) || 0,
      chainCount: face.chain_count == null || face.chain_count === "" ? undefined : Number(face.chain_count)
    }
  };
  if (element.faceElement.chainCount !== undefined && (!Number.isInteger(element.faceElement.chainCount) || element.faceElement.chainCount <= 0)) {
    throw new Error("chain_count must be a positive integer");
  }
  return element;
}

export const plugin_config_schema = [
  {
    key: "token",
    type: "string",
    label: "Shared Token",
    description: "Required shared token checked in x-qqface-token",
    default: ""
  }
];

export async function plugin_init(ctx) {
  logger = ctx.logger;
  loadConfig(ctx);
  ctx.router.getNoAuth("/status", (_req, res) => {
    res.json({
      code: 0,
      data: {
        ready: Boolean(ctx.core?.apis?.MsgApi),
        native_send: true,
        special_effects: [SPECIAL_RAINBOW_DRAGON]
      }
    });
  });
  ctx.router.postNoAuth("/send", async (req, res) => {
    if (unauthorized(req, res)) return;
    try {
      const body = req.body || {};
      const peer = await makePeer(ctx, body);
      const elements = [];
      const text = String(body.text || "").trim();
      if (text) elements.push(makeTextElement(text));
      elements.push(makeFaceElement(body));
      const message = await ctx.core.apis.MsgApi.sendMsg(peer, elements);
      res.json({ code: 0, data: { message_id: message?.msgId || message?.id || "", peer, native: true } });
    } catch (error) {
      logger?.error("native face send failed", error);
      res.status(400).json({ code: -1, message: error?.message || String(error) });
    }
  });
  ctx.router.postNoAuth("/send-special", async (req, res) => {
    if (unauthorized(req, res)) return;
    try {
      const body = req.body || {};
      const effect = String(body.effect || "");
      if (effect !== SPECIAL_RAINBOW_DRAGON) throw new Error("unknown special effect");
      const peer = body.peer || {};
      const peerType = String(peer.type || body.message_type || "").toLowerCase();
      const peerId = peer.id ?? (peerType === "group" ? body.group_id : body.user_id);
      const targetId = positiveId(peerId, peerType === "group" ? "group_id" : "user_id");
      let peerUid = "";
      if (peerType === "private") {
        peerUid = String(await ctx.core?.apis?.UserApi?.getUidByUinV2(targetId) || "");
        if (!peerUid) throw new Error(`cannot resolve private user_id ${targetId} to QQNT uid`);
      } else if (peerType !== "group") {
        throw new Error("peer.type must be private or group");
      }
      const targetPeer = peerType === "private"
        ? { chatType: CHAT_PRIVATE, peerUid, guildId: "" }
        : { chatType: CHAT_GROUP, peerUid: targetId };
      const serverTime = Number(
        ctx.core?.context?.session?.getMSFService?.()?.getServerTime?.()
      );
      const timestamp = Number.isFinite(serverTime) && serverTime > 0
        ? Math.floor(serverTime)
        : Math.floor(Date.now() / 1000);
      let parsed;
      let messageSequence = 0;
      for (let attempt = 0; attempt < 8; attempt++) {
        messageSequence = await nextClientSequence(ctx, targetPeer);
        const packet = buildRainbowDragonPacket({
          peerType,
          peerId: targetId,
          peerUid,
          messageSequence,
          messageRandom: randomPositiveInt32(),
          timestamp
        });
        const reply = await ctx.core?.context?.session?.getMsgService?.()
          ?.sendSsoCmdReqByContend(SEND_MESSAGE_COMMAND, packet);
        parsed = parseSendMessageResponse(reply?.rspbuffer || []);
        if (parsed.result === 0) break;
        if (parsed.result !== 4) throw new Error(`QQ send failed: result=${parsed.result}`);
      }
      if (!parsed || parsed.result !== 0 || !parsed.messageSequence || parsed.messageSequence === "0") {
        throw new Error(`QQ send failed after sequence retry: result=${parsed?.result ?? "unknown"}`);
      }
      res.json({
        code: 0,
        data: {
          effect,
          peer: { type: peerType, id: targetId },
          message_seq: parsed.messageSequence,
          send_time: parsed.sendTime,
          native: true
        }
      });
    } catch (error) {
      logger?.error("special QQ face send failed", error);
      res.status(400).json({ code: -1, message: error?.message || String(error) });
    }
  });
  logger?.info("QQ face enhancer native sender ready");
}

export async function plugin_get_config() {
  return pluginConfig;
}

export async function plugin_set_config(ctx, config) {
  pluginConfig = { ...pluginConfig, ...(config || {}) };
  if (ctx?.configPath) {
    fs.mkdirSync(path.dirname(ctx.configPath), { recursive: true });
    fs.writeFileSync(ctx.configPath, JSON.stringify(pluginConfig, null, 2), "utf8");
  }
}
