# napcat-plugin-qq-face-enhancer

Optional native sender for `astrbot_plugin_qq_face_enhancer`.

Install this companion separately from the AstrBot plugin ZIP by copying this
directory to NapCat's `plugins` directory. Then enable it in NapCat WebUI and
configure a required shared token. The configuration file is normally created
after saving in WebUI:

```text
<NapCat config>\plugins\napcat-plugin-qq-face-enhancer\config.json
```

The value must be a non-empty shared secret. Use the same value for the AstrBot
plugin setting shown below. Do not publish the generated `config.json`.

Configure AstrBot with:

```text
napcat_extended_api_url=http://127.0.0.1:<WebUI port>/plugin/napcat-plugin-qq-face-enhancer/api
napcat_extended_api_token=<the same token>
```

The companion calls `core.apis.MsgApi.sendMsg` with a native `faceElement`, so
extended, super, random, and chain faces are not limited by OneBot's static
`sysface` allow-list.
