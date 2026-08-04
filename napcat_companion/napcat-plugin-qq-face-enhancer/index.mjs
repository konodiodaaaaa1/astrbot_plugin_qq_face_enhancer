import fs from "node:fs";
import path from "node:path";

const ELEMENT_TEXT = 1;
const ELEMENT_FACE = 6;
const CHAT_PRIVATE = 1;
const CHAT_GROUP = 2;
const FACE_NORMAL = 2;
const FACE_ANIMATED = 3;

let pluginConfig = { token: "" };
let logger;

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
    res.json({ code: 0, data: { ready: Boolean(ctx.core?.apis?.MsgApi), native_send: true } });
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
