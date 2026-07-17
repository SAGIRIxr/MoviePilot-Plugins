import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper-pcqpp-6-.js';

const {toDisplayString:_toDisplayString,createTextVNode:_createTextVNode,resolveComponent:_resolveComponent,withCtx:_withCtx,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,createVNode:_createVNode,createElementVNode:_createElementVNode,renderList:_renderList,Fragment:_Fragment,createElementBlock:_createElementBlock} = await importShared('vue');


const _hoisted_1 = { class: "plugin-page" };
const _hoisted_2 = { class: "text-h6" };
const _hoisted_3 = { class: "text-caption" };
const _hoisted_4 = { class: "text-h6" };
const _hoisted_5 = { class: "text-no-wrap" };
const _hoisted_6 = { class: "text-no-wrap" };
const _hoisted_7 = { class: "text-no-wrap" };
const _hoisted_8 = { class: "content-cell" };
const _hoisted_9 = { key: 1 };
const _hoisted_10 = { class: "d-flex mt-4" };

const {ref,onMounted} = await importShared('vue');


const PLUGIN_ID = 'DiscordMsgForward';


const _sfc_main = {
  __name: 'Page',
  props: {
  api: { type: Object, default: () => ({}) },
},
  emits: ['action', 'switch', 'close'],
  setup(__props, { emit: __emit }) {

const props = __props;

const emit = __emit;

const status = ref(null);
const history = ref([]);
const loading = ref(false);
const checking = ref(false);
const message = ref('');
const messageType = ref('info');
const clearDialog = ref(false);

function showMessage(text, type = 'info') {
  message.value = text;
  messageType.value = type;
  setTimeout(() => { message.value = ''; }, 4000);
}

async function loadData() {
  loading.value = true;
  try {
    const [st, hi] = await Promise.all([
      props.api.get(`plugin/${PLUGIN_ID}/status`),
      props.api.get(`plugin/${PLUGIN_ID}/history`),
    ]);
    status.value = st || null;
    history.value = hi?.history || [];
  } catch (e) {
    console.error('加载数据失败', e);
  } finally {
    loading.value = false;
  }
}

async function checkNow() {
  checking.value = true;
  try {
    const res = await props.api.post(`plugin/${PLUGIN_ID}/check`);
    showMessage(res?.message || '已触发检查', 'success');
    setTimeout(loadData, 5000);
  } catch (e) {
    showMessage('触发检查失败', 'error');
  } finally {
    checking.value = false;
  }
}

async function clearHistory() {
  clearDialog.value = false;
  try {
    await props.api.delete(`plugin/${PLUGIN_ID}/history`);
    showMessage('已清空历史', 'success');
    loadData();
  } catch (e) {
    showMessage('清空失败', 'error');
  }
}

onMounted(loadData);

return (_ctx, _cache) => {
  const _component_v_alert = _resolveComponent("v-alert");
  const _component_v_icon = _resolveComponent("v-icon");
  const _component_v_spacer = _resolveComponent("v-spacer");
  const _component_v_btn = _resolveComponent("v-btn");
  const _component_v_card_title = _resolveComponent("v-card-title");
  const _component_v_divider = _resolveComponent("v-divider");
  const _component_v_chip = _resolveComponent("v-chip");
  const _component_v_col = _resolveComponent("v-col");
  const _component_v_row = _resolveComponent("v-row");
  const _component_v_card_text = _resolveComponent("v-card-text");
  const _component_v_card = _resolveComponent("v-card");
  const _component_v_table = _resolveComponent("v-table");
  const _component_v_card_actions = _resolveComponent("v-card-actions");
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
              default: _withCtx(() => [...(_cache[5] || (_cache[5] = [
                _createTextVNode("mdi-monitor-dashboard", -1)
              ]))]),
              _: 1
            }),
            _cache[9] || (_cache[9] = _createTextVNode(" 运行状态 ", -1)),
            _createVNode(_component_v_spacer),
            _createVNode(_component_v_btn, {
              size: "small",
              variant: "tonal",
              color: "success",
              class: "mr-2",
              loading: checking.value,
              "prepend-icon": "mdi-play",
              onClick: checkNow
            }, {
              default: _withCtx(() => [...(_cache[6] || (_cache[6] = [
                _createTextVNode(" 立即检查 ", -1)
              ]))]),
              _: 1
            }, 8, ["loading"]),
            _createVNode(_component_v_btn, {
              size: "small",
              variant: "tonal",
              color: "info",
              class: "mr-2",
              loading: loading.value,
              "prepend-icon": "mdi-refresh",
              onClick: loadData
            }, {
              default: _withCtx(() => [...(_cache[7] || (_cache[7] = [
                _createTextVNode(" 刷新 ", -1)
              ]))]),
              _: 1
            }, 8, ["loading"]),
            _createVNode(_component_v_btn, {
              size: "small",
              variant: "text",
              "prepend-icon": "mdi-cog",
              onClick: _cache[0] || (_cache[0] = $event => (emit('switch')))
            }, {
              default: _withCtx(() => [...(_cache[8] || (_cache[8] = [
                _createTextVNode(" 配置 ", -1)
              ]))]),
              _: 1
            })
          ]),
          _: 1
        }),
        _createVNode(_component_v_divider),
        (status.value)
          ? (_openBlock(), _createBlock(_component_v_card_text, { key: 0 }, {
              default: _withCtx(() => [
                _createVNode(_component_v_row, { dense: "" }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_col, {
                      cols: "6",
                      md: "3"
                    }, {
                      default: _withCtx(() => [
                        _cache[10] || (_cache[10] = _createElementVNode("div", { class: "text-caption" }, "插件状态", -1)),
                        _createVNode(_component_v_chip, {
                          color: status.value.enabled ? 'success' : 'grey',
                          size: "small",
                          variant: "tonal"
                        }, {
                          default: _withCtx(() => [
                            _createTextVNode(_toDisplayString(status.value.enabled ? '已启用' : '未启用'), 1)
                          ]),
                          _: 1
                        }, 8, ["color"])
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_v_col, {
                      cols: "6",
                      md: "3"
                    }, {
                      default: _withCtx(() => [
                        _cache[11] || (_cache[11] = _createElementVNode("div", { class: "text-caption" }, "转发规则", -1)),
                        _createElementVNode("span", _hoisted_2, _toDisplayString(status.value.rules_enabled), 1),
                        _createElementVNode("span", _hoisted_3, " / " + _toDisplayString(status.value.rules_total) + " 条启用", 1)
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_v_col, {
                      cols: "6",
                      md: "3"
                    }, {
                      default: _withCtx(() => [
                        _cache[12] || (_cache[12] = _createElementVNode("div", { class: "text-caption" }, "免打扰暂存", -1)),
                        _createElementVNode("span", _hoisted_4, _toDisplayString(status.value.pending_count), 1),
                        _cache[13] || (_cache[13] = _createElementVNode("span", { class: "text-caption" }, " 条待推送", -1))
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_v_col, {
                      cols: "6",
                      md: "3"
                    }, {
                      default: _withCtx(() => [
                        _cache[14] || (_cache[14] = _createElementVNode("div", { class: "text-caption" }, "Bot Token", -1)),
                        _createVNode(_component_v_chip, {
                          color: status.value.token_set ? 'success' : 'error',
                          size: "small",
                          variant: "tonal"
                        }, {
                          default: _withCtx(() => [
                            _createTextVNode(_toDisplayString(status.value.token_set ? '已配置' : '未配置'), 1)
                          ]),
                          _: 1
                        }, 8, ["color"])
                      ]),
                      _: 1
                    })
                  ]),
                  _: 1
                }),
                (status.value.fail_streak > 0)
                  ? (_openBlock(), _createBlock(_component_v_alert, {
                      key: 0,
                      type: "warning",
                      variant: "tonal",
                      density: "compact",
                      class: "mt-3"
                    }, {
                      default: _withCtx(() => [
                        _createTextVNode(" 已连续 " + _toDisplayString(status.value.fail_streak) + " 次轮询失败" + _toDisplayString(status.value.last_error ? `：${status.value.last_error}` : ''), 1)
                      ]),
                      _: 1
                    }))
                  : _createCommentVNode("", true)
              ]),
              _: 1
            }))
          : _createCommentVNode("", true)
      ]),
      _: 1
    }),
    _createVNode(_component_v_card, null, {
      default: _withCtx(() => [
        _createVNode(_component_v_card_title, { class: "d-flex align-center" }, {
          default: _withCtx(() => [
            _createVNode(_component_v_icon, {
              color: "info",
              class: "mr-2"
            }, {
              default: _withCtx(() => [...(_cache[15] || (_cache[15] = [
                _createTextVNode("mdi-history", -1)
              ]))]),
              _: 1
            }),
            _cache[17] || (_cache[17] = _createTextVNode(" 转发历史 ", -1)),
            _createVNode(_component_v_spacer),
            (history.value.length)
              ? (_openBlock(), _createBlock(_component_v_btn, {
                  key: 0,
                  size: "small",
                  variant: "text",
                  color: "error",
                  "prepend-icon": "mdi-delete-sweep",
                  onClick: _cache[1] || (_cache[1] = $event => (clearDialog.value = true))
                }, {
                  default: _withCtx(() => [...(_cache[16] || (_cache[16] = [
                    _createTextVNode(" 清空 ", -1)
                  ]))]),
                  _: 1
                }))
              : _createCommentVNode("", true)
          ]),
          _: 1
        }),
        _createVNode(_component_v_divider),
        _createVNode(_component_v_card_text, null, {
          default: _withCtx(() => [
            (!history.value.length)
              ? (_openBlock(), _createBlock(_component_v_alert, {
                  key: 0,
                  type: "info",
                  variant: "tonal"
                }, {
                  default: _withCtx(() => [...(_cache[18] || (_cache[18] = [
                    _createTextVNode(" 暂无转发记录 ", -1)
                  ]))]),
                  _: 1
                }))
              : (_openBlock(), _createBlock(_component_v_table, {
                  key: 1,
                  hover: "",
                  density: "compact"
                }, {
                  default: _withCtx(() => [
                    _cache[19] || (_cache[19] = _createElementVNode("thead", null, [
                      _createElementVNode("tr", null, [
                        _createElementVNode("th", { class: "text-start" }, "时间"),
                        _createElementVNode("th", { class: "text-start" }, "规则"),
                        _createElementVNode("th", { class: "text-start" }, "频道"),
                        _createElementVNode("th", { class: "text-start" }, "发送者"),
                        _createElementVNode("th", { class: "text-start" }, "内容"),
                        _createElementVNode("th", { class: "text-start" }, "条数"),
                        _createElementVNode("th", { class: "text-start" }, "提取内容")
                      ])
                    ], -1)),
                    _createElementVNode("tbody", null, [
                      (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(history.value, (h, i) => {
                        return (_openBlock(), _createElementBlock("tr", { key: i }, [
                          _createElementVNode("td", _hoisted_5, _toDisplayString(h.date), 1),
                          _createElementVNode("td", _hoisted_6, _toDisplayString(h.rule || '-'), 1),
                          _createElementVNode("td", null, _toDisplayString(h.channel), 1),
                          _createElementVNode("td", _hoisted_7, _toDisplayString(h.author), 1),
                          _createElementVNode("td", _hoisted_8, _toDisplayString(h.content), 1),
                          _createElementVNode("td", null, _toDisplayString(h.count || 1), 1),
                          _createElementVNode("td", null, [
                            (h.codes)
                              ? (_openBlock(), _createBlock(_component_v_chip, {
                                  key: 0,
                                  color: "success",
                                  size: "small",
                                  variant: "tonal"
                                }, {
                                  default: _withCtx(() => [
                                    _createTextVNode(_toDisplayString(h.codes), 1)
                                  ]),
                                  _: 2
                                }, 1024))
                              : (_openBlock(), _createElementBlock("span", _hoisted_9, "-"))
                          ])
                        ]))
                      }), 128))
                    ])
                  ]),
                  _: 1
                }))
          ]),
          _: 1
        })
      ]),
      _: 1
    }),
    _createElementVNode("div", _hoisted_10, [
      _createVNode(_component_v_spacer),
      _createVNode(_component_v_btn, {
        variant: "text",
        onClick: _cache[2] || (_cache[2] = $event => (emit('close')))
      }, {
        default: _withCtx(() => [...(_cache[20] || (_cache[20] = [
          _createTextVNode("关闭", -1)
        ]))]),
        _: 1
      })
    ]),
    _createVNode(_component_v_dialog, {
      modelValue: clearDialog.value,
      "onUpdate:modelValue": _cache[4] || (_cache[4] = $event => ((clearDialog).value = $event)),
      "max-width": "360"
    }, {
      default: _withCtx(() => [
        _createVNode(_component_v_card, null, {
          default: _withCtx(() => [
            _createVNode(_component_v_card_title, null, {
              default: _withCtx(() => [...(_cache[21] || (_cache[21] = [
                _createTextVNode("清空历史", -1)
              ]))]),
              _: 1
            }),
            _createVNode(_component_v_card_text, null, {
              default: _withCtx(() => [...(_cache[22] || (_cache[22] = [
                _createTextVNode("确定清空全部转发历史记录吗？此操作不可恢复。", -1)
              ]))]),
              _: 1
            }),
            _createVNode(_component_v_card_actions, null, {
              default: _withCtx(() => [
                _createVNode(_component_v_spacer),
                _createVNode(_component_v_btn, {
                  variant: "text",
                  onClick: _cache[3] || (_cache[3] = $event => (clearDialog.value = false))
                }, {
                  default: _withCtx(() => [...(_cache[23] || (_cache[23] = [
                    _createTextVNode("取消", -1)
                  ]))]),
                  _: 1
                }),
                _createVNode(_component_v_btn, {
                  color: "error",
                  onClick: clearHistory
                }, {
                  default: _withCtx(() => [...(_cache[24] || (_cache[24] = [
                    _createTextVNode("清空", -1)
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
const Page = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-299f0c0c"]]);

export { Page as default };
