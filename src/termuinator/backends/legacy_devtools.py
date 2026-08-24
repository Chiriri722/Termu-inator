"""Closed Developer Mode probes for the inherited browser adapter."""

from __future__ import annotations

import json
import math
from typing import Mapping

from ..contracts import Bounds, ErrorCode
from ..errors import TermuinatorError
from .base import (
    BackendConsoleEntry,
    BackendDevtoolsQuery,
    BackendDevtoolsResult,
    BackendDomEntry,
    BackendNetworkEntry,
    BackendPerformanceEntry,
    BackendStyleEntry,
)


_CONSOLE = r"""(function(){
'use strict';const TERMUINATOR_DEVTOOLS_CONSOLE_V1=true;
const key=__REGISTRY_KEY__,options=__OPTIONS__;const registry=window[key];
if(!registry)throw new Error('observation registry unavailable');
if(!registry.devConsole){
  const state={entries:[]};registry.devConsole=state;
  function text(value){try{if(typeof value==='string')return value.slice(0,4096);return JSON.stringify(value).slice(0,4096)}catch(_error){return '[unserializable]'}}
  for(const level of ['debug','info','warn','error']){
    const original=console[level];if(typeof original!=='function')continue;
    console[level]=function(){
      const mapped=level==='warn'?'warning':level;
      state.entries.push({level:mapped,message:Array.from(arguments).map(text).join(' ').slice(0,4096),timestamp:new Date().toISOString()});
      if(state.entries.length>1000)state.entries.splice(0,state.entries.length-1000);
      return original.apply(console,arguments);
    };
  }
}
let entries=registry.devConsole.entries.slice();if(options.level)entries=entries.filter(function(entry){return entry.level===options.level});
const limit=Number(options.limit||100);const truncated=entries.length>limit;entries=entries.slice(-limit);
return {entries:entries,truncated:truncated};
})()"""


_NETWORK = r"""(function(){
'use strict';const TERMUINATOR_DEVTOOLS_NETWORK_V1=true;
const key=__REGISTRY_KEY__,options=__OPTIONS__;const registry=window[key];
if(!registry)throw new Error('observation registry unavailable');
if(!(registry.devNetworkIds instanceof Map))registry.devNetworkIds=new Map();
let counter=Number(registry.devNetworkCounter||0);
function issue(entry){
  const identity=[entry.name,entry.startTime,entry.duration,entry.initiatorType].join('|');let value=registry.devNetworkIds.get(identity);if(value)return value;
  value='request_'+(++counter)+'_'+Math.random().toString(36).slice(2,14);registry.devNetworkIds.set(identity,value);registry.devNetworkCounter=counter;return value;
}
const filter=String(options.url_filter||'');let raw=performance.getEntriesByType('resource').filter(function(entry){return !filter||String(entry.name).includes(filter)});
const limit=Number(options.limit||100);const truncated=raw.length>limit;raw=raw.slice(-limit);
const entries=raw.map(function(entry){
  const responseStatus=Number(entry.responseStatus);const status=Number.isInteger(responseStatus)&&responseStatus>=100&&responseStatus<=599?responseStatus:null;
  return {backend_request_id:issue(entry),method:'GET',url:String(entry.name).slice(0,8192),status:status,
    resource_type:String(entry.initiatorType||'other').slice(0,64),started_at:new Date(performance.timeOrigin+Number(entry.startTime||0)).toISOString(),duration_ms:Math.max(0,Number(entry.duration||0))};
});
return {entries:entries,truncated:truncated};
})()"""


_DOM = r"""(function(){
'use strict';const TERMUINATOR_DEVTOOLS_DOM_V1=true;
const key=__REGISTRY_KEY__,options=__OPTIONS__,targetHandle=__HANDLE__;const registry=window[key];
if(!registry||!(registry.nodes instanceof Map)||!(registry.reverse instanceof WeakMap))throw new Error('observation registry unavailable');
let root=targetHandle?registry.nodes.get(targetHandle):document.documentElement;if(!root||!root.isConnected)return {error:'target_not_found'};
function bounded(value,limit){return String(value==null?'':value).slice(0,limit)}
function issue(element){let handle=registry.reverse.get(element);if(handle)return handle;handle='node_'+(++registry.counter)+'_'+Math.random().toString(36).slice(2,14);registry.reverse.set(element,handle);registry.nodes.set(handle,element);return handle}
function role(element){const value=element.getAttribute&&element.getAttribute('role');if(value)return bounded(value,128);const tag=(element.tagName||'').toLowerCase();if(tag==='a')return 'link';if(tag==='button')return 'button';if(tag==='input'||tag==='textarea')return 'textbox';return 'generic'}
function name(element){return bounded((element.getAttribute&&element.getAttribute('aria-label'))||element.alt||element.title||element.textContent||'',2048).trim()}
const maxDepth=Number(options.max_depth==null?3:options.max_depth);const queue=[[root,0]];const entries=[];let truncated=false;
while(queue.length){const item=queue.shift(),element=item[0],depth=item[1];if(!(element instanceof Element))continue;if(entries.length>=2048){truncated=true;break}
  const rect=element.getBoundingClientRect();entries.push({backend_node_id:issue(element),tag:bounded((element.tagName||'').toLowerCase(),64),role:role(element),name:name(element),text:bounded((element.innerText||element.textContent||'').trim(),4096),x:Number(rect.x),y:Number(rect.y),width:Number(rect.width),height:Number(rect.height)});
  if(depth<maxDepth){for(const child of Array.from(element.children))queue.push([child,depth+1]);if(element.shadowRoot){for(const child of Array.from(element.shadowRoot.children))queue.push([child,depth+1])}}
}
return {entries:entries,truncated:truncated};
})()"""


_STYLE = r"""(function(){
'use strict';const TERMUINATOR_DEVTOOLS_STYLE_V1=true;
const key=__REGISTRY_KEY__,options=__OPTIONS__,targetHandle=__HANDLE__;const registry=window[key];
if(!registry||!(registry.nodes instanceof Map))throw new Error('observation registry unavailable');
const element=registry.nodes.get(targetHandle);if(!element||!element.isConnected)return {error:'target_not_found'};
const defaults=['display','visibility','color','background-color','font-size','font-family','position','z-index'];const properties=options.properties&&options.properties.length?options.properties:defaults;const style=getComputedStyle(element);
const entries=properties.slice(0,128).map(function(name){return {name:String(name).slice(0,128),value:String(style.getPropertyValue(name)||'').slice(0,2048)}});
return {entries:entries,truncated:properties.length>128};
})()"""


_PERFORMANCE = r"""(function(){
'use strict';const TERMUINATOR_DEVTOOLS_PERFORMANCE_V1=true;
const options=__OPTIONS__;const scope=options.scope;const navigation=performance.getEntriesByType('navigation')[0]||null;const resources=performance.getEntriesByType('resource');const entries=[];
function add(name,value,unit){value=Number(value);if(Number.isFinite(value))entries.push({name:name,value:value,unit:unit})}
if(scope==='navigation'||scope==='summary'){
  if(navigation){add('duration',navigation.duration,'ms');add('domContentLoaded',navigation.domContentLoadedEventEnd,'ms');add('loadEvent',navigation.loadEventEnd,'ms');add('transferSize',navigation.transferSize||0,'bytes')}
}
if(scope==='resources'||scope==='summary'){
  add('resourceCount',resources.length,'count');add('resourceDuration',resources.reduce(function(total,item){return total+Number(item.duration||0)},0),'ms');add('resourceTransferSize',resources.reduce(function(total,item){return total+Number(item.transferSize||0)},0),'bytes');
}
return {entries:entries.slice(0,256),truncated:entries.length>256};
})()"""


_TEMPLATES = {
    "console": _CONSOLE,
    "network": _NETWORK,
    "dom": _DOM,
    "style": _STYLE,
    "performance": _PERFORMANCE,
}


def devtools_script(registry_key: str, query: BackendDevtoolsQuery) -> str:
    """Build one fixed probe; caller input is encoded only as JSON data."""

    template = _TEMPLATES[query.query]
    return (
        template.replace("__REGISTRY_KEY__", json.dumps(registry_key))
        .replace("__OPTIONS__", json.dumps(dict(query.parameters), separators=(",", ":")))
        .replace("__HANDLE__", json.dumps(query.backend_node_id))
    )


def normalize_devtools_result(query: str, payload: object) -> BackendDevtoolsResult:
    if not isinstance(payload, Mapping):
        raise _invalid(query, "Developer probe result is not an object")
    if payload.get("error") == "target_not_found" and set(payload) == {"error"}:
        raise TermuinatorError(
            ErrorCode.TARGET_NOT_FOUND,
            "The observed Developer target is no longer connected",
            retryable=True,
            details={"capability": "devtools", "query": query},
        )
    if set(payload) != {"entries", "truncated"}:
        raise _invalid(query, "Developer probe envelope is invalid")
    raw_entries = payload["entries"]
    truncated = payload["truncated"]
    maximum = {"console": 1_000, "network": 1_000, "dom": 2_048, "style": 256, "performance": 256}[query]
    if (
        not isinstance(raw_entries, list)
        or len(raw_entries) > maximum
        or not isinstance(truncated, bool)
    ):
        raise _invalid(query, "Developer probe result is invalid or unbounded")
    try:
        if query == "console":
            entries = tuple(_console(item) for item in raw_entries)
        elif query == "network":
            entries = tuple(_network(item) for item in raw_entries)
        elif query == "dom":
            entries = tuple(_dom(item) for item in raw_entries)
        elif query == "style":
            entries = tuple(_style(item) for item in raw_entries)
        else:
            entries = tuple(_performance(item) for item in raw_entries)
        return BackendDevtoolsResult(query=query, entries=entries, truncated=truncated)
    except TermuinatorError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise _invalid(query, "Developer probe entries are invalid") from exc


def _console(value: object) -> BackendConsoleEntry:
    item = _mapping(value, {"level", "message", "timestamp"})
    return BackendConsoleEntry(
        level=_string(item["level"], 7, minimum=4),
        message=_string(item["message"], 4_096),
        timestamp=_string(item["timestamp"], 64, minimum=1),
    )


def _network(value: object) -> BackendNetworkEntry:
    item = _mapping(
        value,
        {
            "backend_request_id",
            "method",
            "url",
            "status",
            "resource_type",
            "started_at",
            "duration_ms",
        },
    )
    status = item["status"]
    if status is not None and (
        isinstance(status, bool)
        or not isinstance(status, int)
        or not 100 <= status <= 599
    ):
        raise ValueError("network status is invalid")
    duration = item["duration_ms"]
    if duration is not None:
        duration = _number(duration, minimum=0)
    return BackendNetworkEntry(
        backend_request_id=_string(item["backend_request_id"], 256, minimum=1),
        method=_string(item["method"], 16, minimum=1),
        url=_string(item["url"], 8_192),
        status=status,
        resource_type=_string(item["resource_type"], 64),
        started_at=_string(item["started_at"], 64, minimum=1),
        duration_ms=duration,
    )


def _dom(value: object) -> BackendDomEntry:
    item = _mapping(
        value,
        {
            "backend_node_id",
            "tag",
            "role",
            "name",
            "text",
            "x",
            "y",
            "width",
            "height",
        },
    )
    return BackendDomEntry(
        backend_node_id=_string(item["backend_node_id"], 256, minimum=1),
        tag=_string(item["tag"], 64),
        role=_string(item["role"], 128),
        name=_string(item["name"], 2_048),
        text=_string(item["text"], 4_096),
        bounds=Bounds(
            x=_number(item["x"]),
            y=_number(item["y"]),
            width=_number(item["width"]),
            height=_number(item["height"]),
        ),
    )


def _style(value: object) -> BackendStyleEntry:
    item = _mapping(value, {"name", "value"})
    return BackendStyleEntry(
        name=_string(item["name"], 128, minimum=1),
        value=_string(item["value"], 2_048),
    )


def _performance(value: object) -> BackendPerformanceEntry:
    item = _mapping(value, {"name", "value", "unit"})
    return BackendPerformanceEntry(
        name=_string(item["name"], 128, minimum=1),
        value=_number(item["value"]),
        unit=_string(item["unit"], 5, minimum=2),
    )


def _mapping(value: object, fields: set[str]) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError("entry fields are invalid")
    return value


def _string(value: object, maximum: int, *, minimum: int = 0) -> str:
    if not isinstance(value, str) or not minimum <= len(value) <= maximum:
        raise ValueError("string value is invalid or unbounded")
    return value


def _number(value: object, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("numeric value is invalid")
    result = float(value)
    if not math.isfinite(result) or (minimum is not None and result < minimum):
        raise ValueError("numeric value is invalid")
    return result


def _invalid(query: str, message: str) -> TermuinatorError:
    return TermuinatorError(
        ErrorCode.BACKEND_CRASHED,
        message,
        retryable=True,
        details={"capability": "devtools", "query": query},
    )


__all__ = ["devtools_script", "normalize_devtools_result"]
