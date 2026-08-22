import { importShared } from './__federation_fn_import-JrT3xvdd.js';

const {createTextVNode:_createTextVNode,resolveComponent:_resolveComponent,withCtx:_withCtx,createVNode:_createVNode,openBlock:_openBlock,createElementBlock:_createElementBlock} = await importShared('vue');


const _hoisted_1 = { class: "dashboard-widget" };


const _sfc_main = {
  __name: 'Dashboard',
  props: {
  config: { type: Object, default: () => ({}) },
  allowRefresh: { type: Boolean, default: true },
},
  setup(__props) {



return (_ctx, _cache) => {
  const _component_v_icon = _resolveComponent("v-icon");
  const _component_v_card_title = _resolveComponent("v-card-title");
  const _component_v_card_text = _resolveComponent("v-card-text");
  const _component_v_card = _resolveComponent("v-card");

  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    _createVNode(_component_v_card, null, {
      default: _withCtx(() => [
        _createVNode(_component_v_card_title, { class: "text-subtitle-1" }, {
          default: _withCtx(() => [
            _createVNode(_component_v_icon, {
              size: "small",
              class: "mr-1"
            }, {
              default: _withCtx(() => [...(_cache[0] || (_cache[0] = [
                _createTextVNode("mdi-swap-horizontal", -1)
              ]))]),
              _: 1
            }),
            _cache[1] || (_cache[1] = _createTextVNode(" Discord消息转发 ", -1))
          ]),
          _: 1
        }),
        _createVNode(_component_v_card_text, { class: "text-caption" }, {
          default: _withCtx(() => [...(_cache[2] || (_cache[2] = [
            _createTextVNode("运行详情请打开插件详情页查看。", -1)
          ]))]),
          _: 1
        })
      ]),
      _: 1
    })
  ]))
}
}

};

export { _sfc_main as default };
