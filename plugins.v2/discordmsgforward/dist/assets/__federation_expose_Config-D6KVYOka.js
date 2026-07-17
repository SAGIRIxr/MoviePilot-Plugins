import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper-pcqpp-6-.js';

const {toDisplayString:_toDisplayString,createTextVNode:_createTextVNode,resolveComponent:_resolveComponent,withCtx:_withCtx,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,createVNode:_createVNode,renderList:_renderList,Fragment:_Fragment,createElementBlock:_createElementBlock,withModifiers:_withModifiers,createElementVNode:_createElementVNode} = await importShared('vue');


const _hoisted_1 = { class: "plugin-config" };
const _hoisted_2 = { class: "mb-1" };
const _hoisted_3 = { class: "text-caption mb-1" };
const _hoisted_4 = { key: 1 };
const _hoisted_5 = {
  key: 0,
  class: "text-caption text-truncate"
};
const _hoisted_6 = { class: "d-flex" };

const {ref,reactive,computed,onMounted} = await importShared('vue');


const PLUGIN_ID = 'DiscordMsgForward';


const _sfc_main = {
  __name: 'Config',
  props: {
  initialConfig: { type: Object, default: () => ({}) },
  api: { type: Object, default: () => ({}) },
},
  emits: ['save', 'close', 'switch'],
  setup(__props, { emit: __emit }) {

const props = __props;

const emit = __emit;

function defaultRule() {
  return {
    id: Math.random().toString(36).slice(2, 10),
    name: '',
    enabled: true,
    channels: [],
    notify_channels: [],
    keywords: '',
    blocked_keywords: '',
    author_include: '',
    author_exclude: '',
    code_regex: '',
    aggregate: true,
    forward_image: true,
    quiet_hours: '',
    title_template: '',
    text_template: '',
  }
}

const config = reactive({
  enabled: false,
  token: '',
  use_proxy: true,
  interval: 5,
  msgtype: 'Plugin',
  fail_alert: true,
  history_days: 30,
  ...props.initialConfig,
  rules: (props.initialConfig?.rules || []).map(r => ({ ...defaultRule(), ...r })),
});

const channelOptions = ref([]);
const notifierOptions = ref([]);
const msgtypeOptions = ref([]);
const loadingChannels = ref(false);
const showToken = ref(false);
const message = ref('');
const messageType = ref('info');

// 规则编辑弹窗
const dialog = ref(false);
const editIndex = ref(-1);
const editRule = ref(defaultRule());

// 删除确认
const deleteDialog = ref(false);
const deleteIndex = ref(-1);

const channelNameMap = computed(() => {
  const map = {};
  channelOptions.value.forEach(o => { map[o.value] = o.title; });
  return map
});

function channelName(cid) {
  return channelNameMap.value[cid] || cid
}

function showMessage(text, type = 'info') {
  message.value = text;
  messageType.value = type;
  setTimeout(() => { message.value = ''; }, 4000);
}

async function loadOptions() {
  try {
    const [notifiers, msgtypes] = await Promise.all([
      props.api.get(`plugin/${PLUGIN_ID}/notifiers`),
      props.api.get(`plugin/${PLUGIN_ID}/msgtypes`),
    ]);
    notifierOptions.value = notifiers?.options || [];
    msgtypeOptions.value = msgtypes?.options || [];
  } catch (e) {
    console.error('加载选项失败', e);
  }
}

async function loadChannels(refresh = false) {
  loadingChannels.value = true;
  try {
    const res = await props.api.get(`plugin/${PLUGIN_ID}/channels`, { params: { refresh } });
    channelOptions.value = res?.options || [];
    if (refresh) {
      showMessage(`已刷新，共 ${channelOptions.value.length} 个频道`, 'success');
    }
  } catch (e) {
    console.error('加载频道失败', e);
    if (refresh) showMessage('刷新频道列表失败，请检查 Token 和代理', 'error');
  } finally {
    loadingChannels.value = false;
  }
}

function addRule() {
  editIndex.value = -1;
  editRule.value = defaultRule();
  dialog.value = true;
}

function openRule(index) {
  editIndex.value = index;
  editRule.value = JSON.parse(JSON.stringify(config.rules[index]));
  dialog.value = true;
}

function confirmRule() {
  if (!editRule.value.name) {
    editRule.value.name = `规则 ${config.rules.length + 1}`;
  }
  if (editIndex.value >= 0) {
    config.rules.splice(editIndex.value, 1, JSON.parse(JSON.stringify(editRule.value)));
  } else {
    config.rules.push(JSON.parse(JSON.stringify(editRule.value)));
  }
  dialog.value = false;
}

function askDelete(index) {
  deleteIndex.value = index;
  deleteDialog.value = true;
}

function confirmDelete() {
  if (deleteIndex.value >= 0) {
    config.rules.splice(deleteIndex.value, 1);
  }
  deleteDialog.value = false;
  deleteIndex.value = -1;
}

function ruleFilterSummary(rule) {
  const parts = [];
  if (rule.keywords) parts.push(`关键词:${rule.keywords}`);
  if (rule.blocked_keywords) parts.push(`屏蔽:${rule.blocked_keywords}`);
  if (rule.author_include) parts.push(`作者:${rule.author_include}`);
  if (rule.author_exclude) parts.push(`排除作者:${rule.author_exclude}`);
  if (rule.code_regex) parts.push('提取正则');
  return parts.join('　')
}

function saveConfig() {
  if (!config.token) {
    showMessage('请填写 Bot Token', 'error');
    return
  }
  emit('save', JSON.parse(JSON.stringify(config)));
}

onMounted(() => {
  loadOptions();
  loadChannels(false);
});

return (_ctx, _cache) => {
  const _component_v_alert = _resolveComponent("v-alert");
  const _component_v_icon = _resolveComponent("v-icon");
  const _component_v_card_title = _resolveComponent("v-card-title");
  const _component_v_divider = _resolveComponent("v-divider");
  const _component_v_switch = _resolveComponent("v-switch");
  const _component_v_col = _resolveComponent("v-col");
  const _component_v_text_field = _resolveComponent("v-text-field");
  const _component_v_row = _resolveComponent("v-row");
  const _component_v_select = _resolveComponent("v-select");
  const _component_v_card_text = _resolveComponent("v-card-text");
  const _component_v_card = _resolveComponent("v-card");
  const _component_v_spacer = _resolveComponent("v-spacer");
  const _component_v_btn = _resolveComponent("v-btn");
  const _component_v_card_item = _resolveComponent("v-card-item");
  const _component_v_chip = _resolveComponent("v-chip");
  const _component_v_card_actions = _resolveComponent("v-card-actions");
  const _component_v_expansion_panel_title = _resolveComponent("v-expansion-panel-title");
  const _component_v_expansion_panel_text = _resolveComponent("v-expansion-panel-text");
  const _component_v_expansion_panel = _resolveComponent("v-expansion-panel");
  const _component_v_textarea = _resolveComponent("v-textarea");
  const _component_v_expansion_panels = _resolveComponent("v-expansion-panels");
  const _component_v_dialog = _resolveComponent("v-dialog");

  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    (message.value)
      ? (_openBlock(), _createBlock(_component_v_alert, {
          key: 0,
          type: messageType.value,
          variant: "tonal",
          density: "compact",
          class: "mb-3"
        }, {
          default: _withCtx(() => [
            _createTextVNode(_toDisplayString(message.value), 1)
          ]),
          _: 1
        }, 8, ["type"]))
      : _createCommentVNode("", true),
    _createVNode(_component_v_card, { class: "mb-4" }, {
      default: _withCtx(() => [
        _createVNode(_component_v_card_title, { class: "d-flex align-center" }, {
          default: _withCtx(() => [
            _createVNode(_component_v_icon, {
              color: "info",
              class: "mr-2"
            }, {
              default: _withCtx(() => [...(_cache[30] || (_cache[30] = [
                _createTextVNode("mdi-cog", -1)
              ]))]),
              _: 1
            }),
            _cache[31] || (_cache[31] = _createTextVNode(" 全局设置 ", -1))
          ]),
          _: 1
        }),
        _createVNode(_component_v_divider),
        _createVNode(_component_v_card_text, null, {
          default: _withCtx(() => [
            _createVNode(_component_v_row, { dense: "" }, {
              default: _withCtx(() => [
                _createVNode(_component_v_col, {
                  cols: "12",
                  md: "3"
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_switch, {
                      modelValue: config.enabled,
                      "onUpdate:modelValue": _cache[0] || (_cache[0] = $event => ((config.enabled) = $event)),
                      label: "启用插件",
                      color: "primary",
                      "hide-details": ""
                    }, null, 8, ["modelValue"])
                  ]),
                  _: 1
                }),
                _createVNode(_component_v_col, {
                  cols: "12",
                  md: "3"
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_switch, {
                      modelValue: config.use_proxy,
                      "onUpdate:modelValue": _cache[1] || (_cache[1] = $event => ((config.use_proxy) = $event)),
                      label: "使用系统代理",
                      color: "warning",
                      "hide-details": ""
                    }, null, 8, ["modelValue"])
                  ]),
                  _: 1
                }),
                _createVNode(_component_v_col, {
                  cols: "12",
                  md: "3"
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_switch, {
                      modelValue: config.fail_alert,
                      "onUpdate:modelValue": _cache[2] || (_cache[2] = $event => ((config.fail_alert) = $event)),
                      label: "失败告警",
                      color: "error",
                      "hide-details": ""
                    }, null, 8, ["modelValue"])
                  ]),
                  _: 1
                }),
                _createVNode(_component_v_col, {
                  cols: "12",
                  md: "3"
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_text_field, {
                      modelValue: config.interval,
                      "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => ((config.interval) = $event)),
                      modelModifiers: { number: true },
                      label: "轮询间隔(分钟)",
                      type: "number",
                      density: "compact",
                      variant: "outlined",
                      "prepend-inner-icon": "mdi-timer-outline",
                      "hide-details": ""
                    }, null, 8, ["modelValue"])
                  ]),
                  _: 1
                })
              ]),
              _: 1
            }),
            _createVNode(_component_v_row, {
              dense: "",
              class: "mt-2"
            }, {
              default: _withCtx(() => [
                _createVNode(_component_v_col, {
                  cols: "12",
                  md: "6"
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_text_field, {
                      modelValue: config.token,
                      "onUpdate:modelValue": _cache[4] || (_cache[4] = $event => ((config.token) = $event)),
                      label: "Bot Token",
                      type: showToken.value ? 'text' : 'password',
                      "append-inner-icon": showToken.value ? 'mdi-eye-off' : 'mdi-eye',
                      density: "compact",
                      variant: "outlined",
                      "prepend-inner-icon": "mdi-key",
                      hint: "保存后自动拉取 Bot 可见频道列表",
                      "persistent-hint": "",
                      autocomplete: "new-password",
                      "onClick:appendInner": _cache[5] || (_cache[5] = $event => (showToken.value = !showToken.value))
                    }, null, 8, ["modelValue", "type", "append-inner-icon"])
                  ]),
                  _: 1
                }),
                _createVNode(_component_v_col, {
                  cols: "12",
                  md: "3"
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_select, {
                      modelValue: config.msgtype,
                      "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => ((config.msgtype) = $event)),
                      label: "通知类型",
                      items: msgtypeOptions.value,
                      "item-title": "title",
                      "item-value": "value",
                      density: "compact",
                      variant: "outlined",
                      "prepend-inner-icon": "mdi-bell-outline",
                      hint: "所选通知渠道需开启该类型开关",
                      "persistent-hint": ""
                    }, null, 8, ["modelValue", "items"])
                  ]),
                  _: 1
                }),
                _createVNode(_component_v_col, {
                  cols: "12",
                  md: "3"
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_text_field, {
                      modelValue: config.history_days,
                      "onUpdate:modelValue": _cache[7] || (_cache[7] = $event => ((config.history_days) = $event)),
                      modelModifiers: { number: true },
                      label: "历史保留天数",
                      type: "number",
                      density: "compact",
                      variant: "outlined",
                      "prepend-inner-icon": "mdi-history",
                      "hide-details": ""
                    }, null, 8, ["modelValue"])
                  ]),
                  _: 1
                })
              ]),
              _: 1
            })
          ]),
          _: 1
        })
      ]),
      _: 1
    }),
    _createVNode(_component_v_card, { class: "mb-4" }, {
      default: _withCtx(() => [
        _createVNode(_component_v_card_title, { class: "d-flex align-center" }, {
          default: _withCtx(() => [
            _createVNode(_component_v_icon, {
              color: "info",
              class: "mr-2"
            }, {
              default: _withCtx(() => [...(_cache[32] || (_cache[32] = [
                _createTextVNode("mdi-swap-horizontal", -1)
              ]))]),
              _: 1
            }),
            _cache[35] || (_cache[35] = _createTextVNode(" 转发规则 ", -1)),
            _createVNode(_component_v_spacer),
            _createVNode(_component_v_btn, {
              size: "small",
              variant: "tonal",
              color: "info",
              class: "mr-2",
              loading: loadingChannels.value,
              "prepend-icon": "mdi-refresh",
              onClick: _cache[8] || (_cache[8] = $event => (loadChannels(true)))
            }, {
              default: _withCtx(() => [...(_cache[33] || (_cache[33] = [
                _createTextVNode(" 刷新频道列表 ", -1)
              ]))]),
              _: 1
            }, 8, ["loading"]),
            _createVNode(_component_v_btn, {
              size: "small",
              color: "primary",
              "prepend-icon": "mdi-plus",
              onClick: addRule
            }, {
              default: _withCtx(() => [...(_cache[34] || (_cache[34] = [
                _createTextVNode(" 添加规则 ", -1)
              ]))]),
              _: 1
            })
          ]),
          _: 1
        }),
        _createVNode(_component_v_divider),
        _createVNode(_component_v_card_text, null, {
          default: _withCtx(() => [
            (!config.rules.length)
              ? (_openBlock(), _createBlock(_component_v_alert, {
                  key: 0,
                  type: "info",
                  variant: "tonal"
                }, {
                  default: _withCtx(() => [...(_cache[36] || (_cache[36] = [
                    _createTextVNode(" 还没有转发规则，点击右上角「添加规则」创建第一条：选择监听频道和转发渠道即可。 ", -1)
                  ]))]),
                  _: 1
                }))
              : (_openBlock(), _createBlock(_component_v_row, {
                  key: 1,
                  dense: ""
                }, {
                  default: _withCtx(() => [
                    (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(config.rules, (rule, index) => {
                      return (_openBlock(), _createBlock(_component_v_col, {
                        key: rule.id,
                        cols: "12",
                        md: "6",
                        lg: "4"
                      }, {
                        default: _withCtx(() => [
                          _createVNode(_component_v_card, {
                            variant: "tonal",
                            color: rule.enabled ? 'primary' : undefined,
                            class: "rule-card"
                          }, {
                            default: _withCtx(() => [
                              _createVNode(_component_v_card_item, null, {
                                prepend: _withCtx(() => [
                                  _createVNode(_component_v_icon, {
                                    color: rule.enabled ? 'primary' : 'grey'
                                  }, {
                                    default: _withCtx(() => [
                                      _createTextVNode(_toDisplayString(rule.enabled ? 'mdi-send-circle' : 'mdi-send-lock'), 1)
                                    ]),
                                    _: 2
                                  }, 1032, ["color"])
                                ]),
                                append: _withCtx(() => [
                                  _createVNode(_component_v_switch, {
                                    modelValue: rule.enabled,
                                    "onUpdate:modelValue": $event => ((rule.enabled) = $event),
                                    color: "primary",
                                    density: "compact",
                                    "hide-details": "",
                                    onClick: _cache[9] || (_cache[9] = _withModifiers(() => {}, ["stop"]))
                                  }, null, 8, ["modelValue", "onUpdate:modelValue"])
                                ]),
                                default: _withCtx(() => [
                                  _createVNode(_component_v_card_title, { class: "text-subtitle-1" }, {
                                    default: _withCtx(() => [
                                      _createTextVNode(_toDisplayString(rule.name || '未命名规则'), 1)
                                    ]),
                                    _: 2
                                  }, 1024)
                                ]),
                                _: 2
                              }, 1024),
                              _createVNode(_component_v_card_text, { class: "pt-0" }, {
                                default: _withCtx(() => [
                                  _createElementVNode("div", _hoisted_2, [
                                    (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(rule.channels.slice(0, 3), (cid) => {
                                      return (_openBlock(), _createBlock(_component_v_chip, {
                                        key: cid,
                                        size: "x-small",
                                        variant: "outlined",
                                        class: "mr-1 mb-1"
                                      }, {
                                        default: _withCtx(() => [
                                          _createTextVNode(_toDisplayString(channelName(cid)), 1)
                                        ]),
                                        _: 2
                                      }, 1024))
                                    }), 128)),
                                    (rule.channels.length > 3)
                                      ? (_openBlock(), _createBlock(_component_v_chip, {
                                          key: 0,
                                          size: "x-small",
                                          variant: "text",
                                          class: "mb-1"
                                        }, {
                                          default: _withCtx(() => [
                                            _createTextVNode(" +" + _toDisplayString(rule.channels.length - 3), 1)
                                          ]),
                                          _: 2
                                        }, 1024))
                                      : _createCommentVNode("", true),
                                    (!rule.channels.length)
                                      ? (_openBlock(), _createBlock(_component_v_chip, {
                                          key: 1,
                                          size: "x-small",
                                          color: "warning",
                                          variant: "tonal",
                                          class: "mb-1"
                                        }, {
                                          default: _withCtx(() => [...(_cache[37] || (_cache[37] = [
                                            _createTextVNode(" 未选频道 ", -1)
                                          ]))]),
                                          _: 1
                                        }))
                                      : _createCommentVNode("", true)
                                  ]),
                                  _createElementVNode("div", _hoisted_3, [
                                    _createVNode(_component_v_icon, {
                                      size: "x-small",
                                      class: "mr-1"
                                    }, {
                                      default: _withCtx(() => [...(_cache[38] || (_cache[38] = [
                                        _createTextVNode("mdi-send", -1)
                                      ]))]),
                                      _: 1
                                    }),
                                    _createTextVNode(" " + _toDisplayString(rule.notify_channels.length ? rule.notify_channels.join('、') : '全部渠道') + " ", 1),
                                    (rule.quiet_hours)
                                      ? (_openBlock(), _createBlock(_component_v_icon, {
                                          key: 0,
                                          size: "x-small",
                                          class: "ml-2 mr-1"
                                        }, {
                                          default: _withCtx(() => [...(_cache[39] || (_cache[39] = [
                                            _createTextVNode("mdi-sleep", -1)
                                          ]))]),
                                          _: 1
                                        }))
                                      : _createCommentVNode("", true),
                                    (rule.quiet_hours)
                                      ? (_openBlock(), _createElementBlock("span", _hoisted_4, _toDisplayString(rule.quiet_hours), 1))
                                      : _createCommentVNode("", true)
                                  ]),
                                  (ruleFilterSummary(rule))
                                    ? (_openBlock(), _createElementBlock("div", _hoisted_5, [
                                        _createVNode(_component_v_icon, {
                                          size: "x-small",
                                          class: "mr-1"
                                        }, {
                                          default: _withCtx(() => [...(_cache[40] || (_cache[40] = [
                                            _createTextVNode("mdi-filter", -1)
                                          ]))]),
                                          _: 1
                                        }),
                                        _createTextVNode(" " + _toDisplayString(ruleFilterSummary(rule)), 1)
                                      ]))
                                    : _createCommentVNode("", true)
                                ]),
                                _: 2
                              }, 1024),
                              _createVNode(_component_v_card_actions, { class: "pt-0" }, {
                                default: _withCtx(() => [
                                  _createVNode(_component_v_spacer),
                                  _createVNode(_component_v_btn, {
                                    size: "small",
                                    variant: "text",
                                    "prepend-icon": "mdi-pencil",
                                    onClick: $event => (openRule(index))
                                  }, {
                                    default: _withCtx(() => [...(_cache[41] || (_cache[41] = [
                                      _createTextVNode(" 编辑 ", -1)
                                    ]))]),
                                    _: 1
                                  }, 8, ["onClick"]),
                                  _createVNode(_component_v_btn, {
                                    size: "small",
                                    variant: "text",
                                    color: "error",
                                    "prepend-icon": "mdi-delete",
                                    onClick: $event => (askDelete(index))
                                  }, {
                                    default: _withCtx(() => [...(_cache[42] || (_cache[42] = [
                                      _createTextVNode(" 删除 ", -1)
                                    ]))]),
                                    _: 1
                                  }, 8, ["onClick"])
                                ]),
                                _: 2
                              }, 1024)
                            ]),
                            _: 2
                          }, 1032, ["color"])
                        ]),
                        _: 2
                      }, 1024))
                    }), 128))
                  ]),
                  _: 1
                }))
          ]),
          _: 1
        })
      ]),
      _: 1
    }),
    _createElementVNode("div", _hoisted_6, [
      _createVNode(_component_v_spacer),
      _createVNode(_component_v_btn, {
        class: "mr-2",
        variant: "text",
        onClick: _cache[10] || (_cache[10] = $event => (emit('switch')))
      }, {
        default: _withCtx(() => [...(_cache[43] || (_cache[43] = [
          _createTextVNode("详情页", -1)
        ]))]),
        _: 1
      }),
      _createVNode(_component_v_btn, {
        class: "mr-2",
        variant: "text",
        onClick: _cache[11] || (_cache[11] = $event => (emit('close')))
      }, {
        default: _withCtx(() => [...(_cache[44] || (_cache[44] = [
          _createTextVNode("关闭", -1)
        ]))]),
        _: 1
      }),
      _createVNode(_component_v_btn, {
        color: "primary",
        "prepend-icon": "mdi-content-save",
        onClick: saveConfig
      }, {
        default: _withCtx(() => [...(_cache[45] || (_cache[45] = [
          _createTextVNode("保存配置", -1)
        ]))]),
        _: 1
      })
    ]),
    _createVNode(_component_v_dialog, {
      modelValue: dialog.value,
      "onUpdate:modelValue": _cache[27] || (_cache[27] = $event => ((dialog).value = $event)),
      "max-width": "800",
      scrollable: ""
    }, {
      default: _withCtx(() => [
        _createVNode(_component_v_card, null, {
          default: _withCtx(() => [
            _createVNode(_component_v_card_title, { class: "d-flex align-center" }, {
              default: _withCtx(() => [
                _createVNode(_component_v_icon, {
                  color: "info",
                  class: "mr-2"
                }, {
                  default: _withCtx(() => [
                    _createTextVNode(_toDisplayString(editIndex.value >= 0 ? 'mdi-pencil' : 'mdi-plus'), 1)
                  ]),
                  _: 1
                }),
                _createTextVNode(" " + _toDisplayString(editIndex.value >= 0 ? '编辑规则' : '添加规则') + " ", 1),
                _createVNode(_component_v_spacer),
                _createVNode(_component_v_switch, {
                  modelValue: editRule.value.enabled,
                  "onUpdate:modelValue": _cache[12] || (_cache[12] = $event => ((editRule.value.enabled) = $event)),
                  label: "启用",
                  color: "primary",
                  density: "compact",
                  "hide-details": ""
                }, null, 8, ["modelValue"])
              ]),
              _: 1
            }),
            _createVNode(_component_v_divider),
            _createVNode(_component_v_card_text, null, {
              default: _withCtx(() => [
                _createVNode(_component_v_row, { dense: "" }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_col, {
                      cols: "12",
                      md: "6"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_v_text_field, {
                          modelValue: editRule.value.name,
                          "onUpdate:modelValue": _cache[13] || (_cache[13] = $event => ((editRule.value.name) = $event)),
                          label: "规则名称",
                          placeholder: "如：WOS 礼包码",
                          density: "compact",
                          variant: "outlined",
                          "prepend-inner-icon": "mdi-tag"
                        }, null, 8, ["modelValue"])
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_v_col, {
                      cols: "12",
                      md: "6"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_v_text_field, {
                          modelValue: editRule.value.quiet_hours,
                          "onUpdate:modelValue": _cache[14] || (_cache[14] = $event => ((editRule.value.quiet_hours) = $event)),
                          label: "免打扰时段（可选）",
                          placeholder: "23:00-08:00，留空不启用",
                          density: "compact",
                          variant: "outlined",
                          "prepend-inner-icon": "mdi-sleep",
                          hint: "时段内消息暂存，结束后汇总推送",
                          "persistent-hint": ""
                        }, null, 8, ["modelValue"])
                      ]),
                      _: 1
                    })
                  ]),
                  _: 1
                }),
                _createVNode(_component_v_row, { dense: "" }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_col, { cols: "12" }, {
                      default: _withCtx(() => [
                        _createVNode(_component_v_select, {
                          modelValue: editRule.value.channels,
                          "onUpdate:modelValue": _cache[15] || (_cache[15] = $event => ((editRule.value.channels) = $event)),
                          label: "监听频道",
                          items: channelOptions.value,
                          "item-title": "title",
                          "item-value": "value",
                          multiple: "",
                          chips: "",
                          "closable-chips": "",
                          clearable: "",
                          density: "compact",
                          variant: "outlined",
                          "prepend-inner-icon": "mdi-pound",
                          loading: loadingChannels.value,
                          "no-data-text": "暂无频道：请先在全局设置填写 Token 并保存，或点击「刷新频道列表」"
                        }, null, 8, ["modelValue", "items", "loading"])
                      ]),
                      _: 1
                    })
                  ]),
                  _: 1
                }),
                _createVNode(_component_v_row, { dense: "" }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_col, { cols: "12" }, {
                      default: _withCtx(() => [
                        _createVNode(_component_v_select, {
                          modelValue: editRule.value.notify_channels,
                          "onUpdate:modelValue": _cache[16] || (_cache[16] = $event => ((editRule.value.notify_channels) = $event)),
                          label: "转发渠道",
                          items: notifierOptions.value,
                          "item-title": "title",
                          "item-value": "value",
                          multiple: "",
                          chips: "",
                          "closable-chips": "",
                          clearable: "",
                          density: "compact",
                          variant: "outlined",
                          "prepend-inner-icon": "mdi-send-circle",
                          hint: "留空 = 发送到全部启用的通知渠道",
                          "persistent-hint": ""
                        }, null, 8, ["modelValue", "items"])
                      ]),
                      _: 1
                    })
                  ]),
                  _: 1
                }),
                _createVNode(_component_v_row, { dense: "" }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_col, {
                      cols: "12",
                      md: "3"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_v_switch, {
                          modelValue: editRule.value.aggregate,
                          "onUpdate:modelValue": _cache[17] || (_cache[17] = $event => ((editRule.value.aggregate) = $event)),
                          label: "消息聚合",
                          color: "info",
                          density: "compact",
                          "hide-details": ""
                        }, null, 8, ["modelValue"])
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_v_col, {
                      cols: "12",
                      md: "3"
                    }, {
                      default: _withCtx(() => [
                        _createVNode(_component_v_switch, {
                          modelValue: editRule.value.forward_image,
                          "onUpdate:modelValue": _cache[18] || (_cache[18] = $event => ((editRule.value.forward_image) = $event)),
                          label: "图片转发",
                          color: "info",
                          density: "compact",
                          "hide-details": ""
                        }, null, 8, ["modelValue"])
                      ]),
                      _: 1
                    })
                  ]),
                  _: 1
                }),
                _createVNode(_component_v_expansion_panels, {
                  variant: "accordion",
                  class: "mt-2"
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_expansion_panel, null, {
                      default: _withCtx(() => [
                        _createVNode(_component_v_expansion_panel_title, null, {
                          default: _withCtx(() => [
                            _createVNode(_component_v_icon, {
                              size: "small",
                              class: "mr-2"
                            }, {
                              default: _withCtx(() => [...(_cache[46] || (_cache[46] = [
                                _createTextVNode("mdi-filter", -1)
                              ]))]),
                              _: 1
                            }),
                            _cache[47] || (_cache[47] = _createTextVNode(" 过滤规则（可选，留空全部转发） ", -1))
                          ]),
                          _: 1
                        }),
                        _createVNode(_component_v_expansion_panel_text, null, {
                          default: _withCtx(() => [
                            _createVNode(_component_v_row, { dense: "" }, {
                              default: _withCtx(() => [
                                _createVNode(_component_v_col, {
                                  cols: "12",
                                  md: "6"
                                }, {
                                  default: _withCtx(() => [
                                    _createVNode(_component_v_text_field, {
                                      modelValue: editRule.value.keywords,
                                      "onUpdate:modelValue": _cache[19] || (_cache[19] = $event => ((editRule.value.keywords) = $event)),
                                      label: "关键词（白名单）",
                                      placeholder: "含任一关键词才转发，逗号或 | 分隔",
                                      density: "compact",
                                      variant: "outlined",
                                      "prepend-inner-icon": "mdi-text-search"
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                }),
                                _createVNode(_component_v_col, {
                                  cols: "12",
                                  md: "6"
                                }, {
                                  default: _withCtx(() => [
                                    _createVNode(_component_v_text_field, {
                                      modelValue: editRule.value.blocked_keywords,
                                      "onUpdate:modelValue": _cache[20] || (_cache[20] = $event => ((editRule.value.blocked_keywords) = $event)),
                                      label: "屏蔽词（黑名单）",
                                      placeholder: "含任一屏蔽词不转发",
                                      density: "compact",
                                      variant: "outlined",
                                      "prepend-inner-icon": "mdi-text-box-remove"
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                }),
                                _createVNode(_component_v_col, {
                                  cols: "12",
                                  md: "6"
                                }, {
                                  default: _withCtx(() => [
                                    _createVNode(_component_v_text_field, {
                                      modelValue: editRule.value.author_include,
                                      "onUpdate:modelValue": _cache[21] || (_cache[21] = $event => ((editRule.value.author_include) = $event)),
                                      label: "只转发这些作者",
                                      placeholder: "用户名精确匹配，不分大小写",
                                      density: "compact",
                                      variant: "outlined",
                                      "prepend-inner-icon": "mdi-account-check"
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                }),
                                _createVNode(_component_v_col, {
                                  cols: "12",
                                  md: "6"
                                }, {
                                  default: _withCtx(() => [
                                    _createVNode(_component_v_text_field, {
                                      modelValue: editRule.value.author_exclude,
                                      "onUpdate:modelValue": _cache[22] || (_cache[22] = $event => ((editRule.value.author_exclude) = $event)),
                                      label: "屏蔽这些作者",
                                      placeholder: "用户名精确匹配，不分大小写",
                                      density: "compact",
                                      variant: "outlined",
                                      "prepend-inner-icon": "mdi-account-cancel"
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                })
                              ]),
                              _: 1
                            })
                          ]),
                          _: 1
                        })
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_v_expansion_panel, null, {
                      default: _withCtx(() => [
                        _createVNode(_component_v_expansion_panel_title, null, {
                          default: _withCtx(() => [
                            _createVNode(_component_v_icon, {
                              size: "small",
                              class: "mr-2"
                            }, {
                              default: _withCtx(() => [...(_cache[48] || (_cache[48] = [
                                _createTextVNode("mdi-tune", -1)
                              ]))]),
                              _: 1
                            }),
                            _cache[49] || (_cache[49] = _createTextVNode(" 高级选项（可选，默认即可） ", -1))
                          ]),
                          _: 1
                        }),
                        _createVNode(_component_v_expansion_panel_text, null, {
                          default: _withCtx(() => [
                            _createVNode(_component_v_row, { dense: "" }, {
                              default: _withCtx(() => [
                                _createVNode(_component_v_col, { cols: "12" }, {
                                  default: _withCtx(() => [
                                    _createVNode(_component_v_text_field, {
                                      modelValue: editRule.value.code_regex,
                                      "onUpdate:modelValue": _cache[23] || (_cache[23] = $event => ((editRule.value.code_regex) = $event)),
                                      label: "内容提取正则（如礼包码）",
                                      placeholder: "如：[A-Za-z0-9]{6,20}，留空不提取",
                                      density: "compact",
                                      variant: "outlined",
                                      "prepend-inner-icon": "mdi-regex",
                                      hint: "命中内容在通知中单独列出，对应模板变量 {codes}",
                                      "persistent-hint": ""
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                }),
                                _createVNode(_component_v_col, {
                                  cols: "12",
                                  md: "5"
                                }, {
                                  default: _withCtx(() => [
                                    _createVNode(_component_v_text_field, {
                                      modelValue: editRule.value.title_template,
                                      "onUpdate:modelValue": _cache[24] || (_cache[24] = $event => ((editRule.value.title_template) = $event)),
                                      label: "标题模板",
                                      placeholder: "【Discord | {channel}】",
                                      density: "compact",
                                      variant: "outlined",
                                      "prepend-inner-icon": "mdi-format-title"
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                }),
                                _createVNode(_component_v_col, {
                                  cols: "12",
                                  md: "7"
                                }, {
                                  default: _withCtx(() => [
                                    _createVNode(_component_v_textarea, {
                                      modelValue: editRule.value.text_template,
                                      "onUpdate:modelValue": _cache[25] || (_cache[25] = $event => ((editRule.value.text_template) = $event)),
                                      label: "内容模板",
                                      rows: "3",
                                      placeholder: "{content}\\n\\n🎁 提取内容：{codes}\\n\\n👤 {author}  🕐 {time}",
                                      density: "compact",
                                      variant: "outlined",
                                      "prepend-inner-icon": "mdi-text",
                                      hint: "变量：{channel} {author} {content} {codes} {time} {count}；提取内容为空时含 {codes} 的行自动隐藏",
                                      "persistent-hint": ""
                                    }, null, 8, ["modelValue"])
                                  ]),
                                  _: 1
                                })
                              ]),
                              _: 1
                            })
                          ]),
                          _: 1
                        })
                      ]),
                      _: 1
                    })
                  ]),
                  _: 1
                })
              ]),
              _: 1
            }),
            _createVNode(_component_v_divider),
            _createVNode(_component_v_card_actions, null, {
              default: _withCtx(() => [
                _createVNode(_component_v_spacer),
                _createVNode(_component_v_btn, {
                  variant: "text",
                  onClick: _cache[26] || (_cache[26] = $event => (dialog.value = false))
                }, {
                  default: _withCtx(() => [...(_cache[50] || (_cache[50] = [
                    _createTextVNode("取消", -1)
                  ]))]),
                  _: 1
                }),
                _createVNode(_component_v_btn, {
                  color: "primary",
                  onClick: confirmRule
                }, {
                  default: _withCtx(() => [...(_cache[51] || (_cache[51] = [
                    _createTextVNode("确定", -1)
                  ]))]),
                  _: 1
                })
              ]),
              _: 1
            })
          ]),
          _: 1
        })
      ]),
      _: 1
    }, 8, ["modelValue"]),
    _createVNode(_component_v_dialog, {
      modelValue: deleteDialog.value,
      "onUpdate:modelValue": _cache[29] || (_cache[29] = $event => ((deleteDialog).value = $event)),
      "max-width": "360"
    }, {
      default: _withCtx(() => [
        _createVNode(_component_v_card, null, {
          default: _withCtx(() => [
            _createVNode(_component_v_card_title, null, {
              default: _withCtx(() => [...(_cache[52] || (_cache[52] = [
                _createTextVNode("删除规则", -1)
              ]))]),
              _: 1
            }),
            _createVNode(_component_v_card_text, null, {
              default: _withCtx(() => [
                _createTextVNode(" 确定删除规则「" + _toDisplayString(deleteIndex.value >= 0 && config.rules[deleteIndex.value] ? config.rules[deleteIndex.value].name || '未命名规则' : '') + "」吗？ ", 1)
              ]),
              _: 1
            }),
            _createVNode(_component_v_card_actions, null, {
              default: _withCtx(() => [
                _createVNode(_component_v_spacer),
                _createVNode(_component_v_btn, {
                  variant: "text",
                  onClick: _cache[28] || (_cache[28] = $event => (deleteDialog.value = false))
                }, {
                  default: _withCtx(() => [...(_cache[53] || (_cache[53] = [
                    _createTextVNode("取消", -1)
                  ]))]),
                  _: 1
                }),
                _createVNode(_component_v_btn, {
                  color: "error",
                  onClick: confirmDelete
                }, {
                  default: _withCtx(() => [...(_cache[54] || (_cache[54] = [
                    _createTextVNode("删除", -1)
                  ]))]),
                  _: 1
                })
              ]),
              _: 1
            })
          ]),
          _: 1
        })
      ]),
      _: 1
    }, 8, ["modelValue"])
  ]))
}
}

};
const Config = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-c9b2699f"]]);

export { Config as default };
