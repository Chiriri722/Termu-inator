"""Closed DOM probes used only inside the inherited Pilot adapter."""

from __future__ import annotations

import json
import math
import re
from typing import Any, Mapping

from ..contracts import Bounds, ErrorCode
from ..errors import TermuinatorError
from .base import RawInteractiveElement


_HANDLE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{7,255}$")
_MAX_ELEMENTS = 512


_OBSERVE_TEMPLATE = r"""(function(){
'use strict';
const TERMUINATOR_OBSERVE_V1=true;
const registryKey=__REGISTRY_KEY__;
let registry=window[registryKey];
if(!registry){
  registry={nodes:new Map(),reverse:new WeakMap(),counter:0,domVersion:0};
  Object.defineProperty(window,registryKey,{value:registry,writable:false,configurable:false,enumerable:false});
  const observer=new MutationObserver(function(){registry.domVersion=Math.min(2147483647,registry.domVersion+1);});
  observer.observe(document,{subtree:true,childList:true,attributes:true,characterData:true});
  registry.observer=observer;
}
if(!(registry.nodes instanceof Map)||!(registry.reverse instanceof WeakMap))throw new Error('registry invalid');
const output=[];const seen=new Set();
const selector='a[href],button,input,textarea,select,summary,[role],[contenteditable="true"],[tabindex]';
function bounded(value,limit){return String(value==null?'':value).slice(0,limit)}
function descriptor(element,index){
  const tag=bounded((element.tagName||'node').toLowerCase(),32);
  const id=element.id?'#'+bounded(element.id,64):'';
  return bounded(tag+id+'['+index+']',128);
}
function roleFor(element){
  const explicit=element.getAttribute&&element.getAttribute('role');if(explicit)return bounded(explicit,64);
  const tag=(element.tagName||'').toLowerCase();const type=bounded(element.type,64).toLowerCase();
  if(tag==='a'&&element.href)return 'link';if(tag==='button'||tag==='summary')return 'button';
  if(tag==='select')return 'combobox';if(type==='checkbox')return 'checkbox';if(type==='radio')return 'radio';
  if(tag==='input'||tag==='textarea'||element.isContentEditable)return 'textbox';return 'generic';
}
function nameFor(element){
  let value=element.getAttribute&&element.getAttribute('aria-label');if(value)return bounded(value,512);
  const labelled=element.getAttribute&&element.getAttribute('aria-labelledby');
  if(labelled){const parts=labelled.split(/\s+/).map(function(id){const node=element.ownerDocument.getElementById(id);return node?node.textContent:''});value=parts.join(' ').trim();if(value)return bounded(value,512)}
  if(element.labels&&element.labels.length){value=Array.from(element.labels).map(function(label){return label.textContent||''}).join(' ').trim();if(value)return bounded(value,512)}
  value=element.alt||element.title||element.placeholder||element.textContent||'';return bounded(String(value).trim(),512);
}
function issue(element){
  let handle=registry.reverse.get(element);if(handle)return handle;
  const bytes=new Uint8Array(12);if(window.crypto&&window.crypto.getRandomValues)window.crypto.getRandomValues(bytes);
  const random=Array.from(bytes).map(function(value){return value.toString(16).padStart(2,'0')}).join('');
  handle='node_'+(++registry.counter)+'_'+(random||Date.now().toString(36));
  registry.reverse.set(element,handle);registry.nodes.set(handle,element);return handle;
}
function visit(root,framePath,shadowPath,offsetX,offsetY){
  if(output.length>=512||!root||!root.querySelectorAll)return;
  const candidates=Array.from(root.querySelectorAll(selector));
  for(const element of candidates){
    if(output.length>=512)break;
    const rect=element.getBoundingClientRect();const style=element.ownerDocument.defaultView.getComputedStyle(element);
    const visible=!!(rect.width>0&&rect.height>0&&style.display!=='none'&&style.visibility!=='hidden'&&Number(style.opacity)!==0);
    const type=bounded(element.type||'',64).toLowerCase();
    const handle=issue(element);seen.add(handle);
    output.push({
      backend_node_id:handle,role:roleFor(element),accessible_name:nameFor(element),
      text:bounded((element.innerText||element.textContent||'').trim(),2048),
      tag:bounded((element.tagName||'').toLowerCase(),64),type:type,
      x:Number(rect.x)+offsetX,y:Number(rect.y)+offsetY,width:Number(rect.width),height:Number(rect.height),
      visible:visible,enabled:!(element.disabled||element.getAttribute('aria-disabled')==='true'),
      editable:!!(element.isContentEditable||element.tagName==='TEXTAREA'||(element.tagName==='INPUT'&&!['button','submit','reset','checkbox','radio','file','hidden'].includes(type))),
      checked:(type==='checkbox'||type==='radio')?!!element.checked:null,
      frame_path:framePath,shadow_path:shadowPath
    });
  }
  const all=Array.from(root.querySelectorAll('*'));
  for(let index=0;index<all.length&&output.length<512;index++){
    const element=all[index];
    if(element.shadowRoot)visit(element.shadowRoot,framePath,shadowPath.concat([descriptor(element,index)]),offsetX,offsetY);
  }
  if(root.nodeType===9){
    const frames=Array.from(root.querySelectorAll('iframe'));
    for(let index=0;index<frames.length&&output.length<512;index++){
      const frame=frames[index];try{const child=frame.contentDocument;if(!child)continue;const rect=frame.getBoundingClientRect();visit(child,framePath.concat([descriptor(frame,index)]),[],offsetX+Number(rect.x),offsetY+Number(rect.y))}catch(_error){}
    }
  }
}
visit(document,[],[],0,0);
for(const entry of Array.from(registry.nodes.entries())){if(!seen.has(entry[0])||!entry[1].isConnected)registry.nodes.delete(entry[0])}
return {ready_state:bounded(document.readyState||'unknown',64),dom_version:registry.domVersion,elements:output};
})()"""


_STATE_TEMPLATE = r"""(function(){
'use strict';
const TERMUINATOR_ELEMENT_STATE_V1=true;
const registry=window[__REGISTRY_KEY__];const handle=__HANDLE__;
if(!registry||!(registry.nodes instanceof Map))return null;
const element=registry.nodes.get(handle);if(!element||!element.isConnected){registry.nodes.delete(handle);return null}
const rect=element.getBoundingClientRect();let x=Number(rect.x),y=Number(rect.y);let view=element.ownerDocument.defaultView;
try{while(view&&view.frameElement){const frameRect=view.frameElement.getBoundingClientRect();x+=Number(frameRect.x);y+=Number(frameRect.y);view=view.parent}}catch(_error){}
const style=element.ownerDocument.defaultView.getComputedStyle(element);const type=String(element.type||'').toLowerCase();
const sensitive=type==='password'||element.autocomplete==='one-time-code';
return {connected:true,x:x,y:y,width:Number(rect.width),height:Number(rect.height),
visible:!!(rect.width>0&&rect.height>0&&style.display!=='none'&&style.visibility!=='hidden'&&Number(style.opacity)!==0),
enabled:!(element.disabled||element.getAttribute('aria-disabled')==='true'),
value:sensitive?null:('value' in element?String(element.value).slice(0,100000):null),
checked:(type==='checkbox'||type==='radio')?!!element.checked:null,
selected:element.tagName==='SELECT'?String(element.value).slice(0,10000):null,
hovered:!!(element.matches&&element.matches(':hover')),scroll_x:Number(window.scrollX||0),scroll_y:Number(window.scrollY||0),
dom_version:Number(registry.domVersion||0)};
})()"""


_PAGE_STATE_TEMPLATE = r"""(function(){
'use strict';const TERMUINATOR_PAGE_STATE_V1=true;
const registry=window[__REGISTRY_KEY__];if(!registry)return null;
return {scroll_x:Number(window.scrollX||0),scroll_y:Number(window.scrollY||0),dom_version:Number(registry.domVersion||0)};
})()"""


_SELECT_TEMPLATE = r"""(function(){
'use strict';const TERMUINATOR_SELECT_V1=true;
const registry=window[__REGISTRY_KEY__],handle=__HANDLE__,value=__VALUE__;
if(!registry||!(registry.nodes instanceof Map))return {error:'target_not_found'};
const element=registry.nodes.get(handle);if(!element||!element.isConnected)return {error:'target_not_found'};
if(String(element.tagName||'').toLowerCase()!=='select')return {error:'invalid_target'};
element.focus();element.value=value;if(element.value!==value)return {error:'value_not_found'};
element.dispatchEvent(new Event('input',{bubbles:true}));element.dispatchEvent(new Event('change',{bubbles:true}));return {dispatched:true};
})()"""


_CHECK_TEMPLATE = r"""(function(){
'use strict';const TERMUINATOR_CHECK_V1=true;
const registry=window[__REGISTRY_KEY__],handle=__HANDLE__,checked=__CHECKED__;
if(!registry||!(registry.nodes instanceof Map))return {error:'target_not_found'};
const element=registry.nodes.get(handle);if(!element||!element.isConnected)return {error:'target_not_found'};
const type=String(element.type||'').toLowerCase();if(type!=='checkbox'&&type!=='radio')return {error:'invalid_target'};
element.focus();element.checked=checked;element.dispatchEvent(new Event('input',{bubbles:true}));element.dispatchEvent(new Event('change',{bubbles:true}));return {dispatched:true};
})()"""


def observe_script(registry_key: str) -> str:
    return _OBSERVE_TEMPLATE.replace("__REGISTRY_KEY__", json.dumps(registry_key))


def element_state_script(registry_key: str, backend_node_id: str) -> str:
    return (
        _STATE_TEMPLATE.replace("__REGISTRY_KEY__", json.dumps(registry_key))
        .replace("__HANDLE__", json.dumps(backend_node_id))
    )


def page_state_script(registry_key: str) -> str:
    return _PAGE_STATE_TEMPLATE.replace("__REGISTRY_KEY__", json.dumps(registry_key))


def select_script(registry_key: str, backend_node_id: str, value: str) -> str:
    return (
        _SELECT_TEMPLATE.replace("__REGISTRY_KEY__", json.dumps(registry_key))
        .replace("__HANDLE__", json.dumps(backend_node_id))
        .replace("__VALUE__", json.dumps(value))
    )


def check_script(registry_key: str, backend_node_id: str, checked: bool) -> str:
    return (
        _CHECK_TEMPLATE.replace("__REGISTRY_KEY__", json.dumps(registry_key))
        .replace("__HANDLE__", json.dumps(backend_node_id))
        .replace("__CHECKED__", json.dumps(checked))
    )


def normalize_observation(
    payload: object,
) -> tuple[str, int, tuple[RawInteractiveElement, ...]]:
    if not isinstance(payload, Mapping):
        raise _invalid("DOM observation is not an object")
    ready_state = payload.get("ready_state")
    dom_version = payload.get("dom_version")
    elements = payload.get("elements")
    if (
        not isinstance(ready_state, str)
        or not 1 <= len(ready_state) <= 64
        or isinstance(dom_version, bool)
        or not isinstance(dom_version, int)
        or not 0 <= dom_version <= 2_147_483_647
        or not isinstance(elements, list)
        or len(elements) > _MAX_ELEMENTS
    ):
        raise _invalid("DOM observation envelope is invalid or unbounded")
    normalized: list[RawInteractiveElement] = []
    for item in elements:
        if not isinstance(item, Mapping):
            raise _invalid("DOM element entry is not an object")
        handle = item.get("backend_node_id")
        if not isinstance(handle, str) or not _HANDLE.fullmatch(handle):
            raise _invalid("DOM element handle is invalid")
        paths: dict[str, tuple[str, ...]] = {}
        for name in ("frame_path", "shadow_path"):
            raw_path = item.get(name, [])
            if (
                not isinstance(raw_path, list)
                or len(raw_path) > 16
                or any(
                    not isinstance(value, str) or not 1 <= len(value) <= 128
                    for value in raw_path
                )
            ):
                raise _invalid(f"DOM element {name} is invalid")
            paths[name] = tuple(raw_path)
        checked = item.get("checked")
        if checked is not None and not isinstance(checked, bool):
            raise _invalid("DOM checked state is invalid")
        flags: dict[str, bool] = {}
        for name in ("visible", "enabled", "editable"):
            value = item.get(name)
            if not isinstance(value, bool):
                raise _invalid(f"DOM {name} state is invalid")
            flags[name] = value
        try:
            bounds = Bounds(
                x=_number(item.get("x")),
                y=_number(item.get("y")),
                width=_number(item.get("width")),
                height=_number(item.get("height")),
            )
            normalized.append(
                RawInteractiveElement(
                    backend_node_id=handle,
                    role=_string(item.get("role"), 64, default="generic"),
                    accessible_name=_string(item.get("accessible_name"), 512),
                    text=_string(item.get("text"), 2_048),
                    tag=_string(item.get("tag"), 64),
                    type=_string(item.get("type"), 64),
                    bounds=bounds,
                    visible=flags["visible"],
                    enabled=flags["enabled"],
                    editable=flags["editable"],
                    checked=checked,
                    frame_path=paths["frame_path"],
                    shadow_path=paths["shadow_path"],
                )
            )
        except (TypeError, ValueError) as exc:
            raise _invalid("DOM element values are invalid") from exc
    return ready_state, dom_version, tuple(normalized)


def normalize_element_state(payload: object) -> Mapping[str, Any] | None:
    if payload is None:
        return None
    if not isinstance(payload, Mapping) or payload.get("connected") is not True:
        raise _invalid("DOM element state is invalid")
    result: dict[str, Any] = {"connected": True}
    for name in ("x", "y", "width", "height", "scroll_x", "scroll_y"):
        result[name] = _number(payload.get(name))
    for name in ("visible", "enabled", "hovered"):
        value = payload.get(name)
        if not isinstance(value, bool):
            raise _invalid(f"DOM element {name} state is invalid")
        result[name] = value
    for name, maximum in (("value", 100_000), ("selected", 10_000)):
        value = payload.get(name)
        if value is not None and (not isinstance(value, str) or len(value) > maximum):
            raise _invalid(f"DOM element {name} state is invalid")
        result[name] = value
    checked = payload.get("checked")
    if checked is not None and not isinstance(checked, bool):
        raise _invalid("DOM element checked state is invalid")
    result["checked"] = checked
    dom_version = payload.get("dom_version")
    if (
        isinstance(dom_version, bool)
        or not isinstance(dom_version, int)
        or not 0 <= dom_version <= 2_147_483_647
    ):
        raise _invalid("DOM element version is invalid")
    result["dom_version"] = dom_version
    return result


def normalize_page_state(payload: object) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping) or set(payload) != {
        "scroll_x",
        "scroll_y",
        "dom_version",
    }:
        raise _invalid("Page action state is invalid", capability="act")
    dom_version = payload["dom_version"]
    if (
        isinstance(dom_version, bool)
        or not isinstance(dom_version, int)
        or not 0 <= dom_version <= 2_147_483_647
    ):
        raise _invalid("Page action version is invalid", capability="act")
    try:
        return {
            "scroll_x": _number(payload["scroll_x"]),
            "scroll_y": _number(payload["scroll_y"]),
            "dom_version": dom_version,
        }
    except (TypeError, ValueError) as exc:
        raise _invalid("Page action state is invalid", capability="act") from exc


def normalize_mutation_result(payload: object) -> None:
    if isinstance(payload, Mapping) and set(payload) == {"dispatched"}:
        if payload["dispatched"] is True:
            return
    if isinstance(payload, Mapping) and set(payload) == {"error"} and payload.get(
        "error"
    ) in {"target_not_found", "invalid_target", "value_not_found"}:
        raise TermuinatorError(
            ErrorCode.TARGET_NOT_FOUND,
            "The observed browser target cannot perform this action",
            retryable=True,
            details={"capability": "act"},
        )
    raise _invalid("Element mutation result is invalid", capability="act")


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("value is not numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("value is not finite")
    return result


def _string(value: object, maximum: int, *, default: str = "") -> str:
    if value is None:
        return default
    if not isinstance(value, str) or len(value) > maximum:
        raise ValueError("value is not a bounded string")
    return value


def _invalid(message: str, *, capability: str = "observe") -> TermuinatorError:
    return TermuinatorError(
        ErrorCode.BACKEND_CRASHED,
        message,
        retryable=True,
        details={"capability": capability},
    )


__all__ = [
    "check_script",
    "element_state_script",
    "normalize_mutation_result",
    "normalize_element_state",
    "normalize_observation",
    "normalize_page_state",
    "observe_script",
    "page_state_script",
    "select_script",
]
