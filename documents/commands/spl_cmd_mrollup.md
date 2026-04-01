---
 command: mrollup
 source_url: https://docs.splunk.com/Documentation/Splunk/latest/SearchReference/Mrollup
 title: mrollup
 download_date: 2026-02-03 09:11:57
---

 ## Syntax
mrollup (source=<string>) (target=<string>) (file=<string>)? (span=<string:timespan>) (aggregate=(<mrollup-aggregate-func>("#"<mrollup-aggregate-func>)?)*)? (dimension-list=(<string>,<string>))? (dimension-list-type=(excluded|included))? (metric-list=(<string>,<string>))? (metric-list-type=(excluded|included))? (metric-overrides=(<string>;(<mrollup-aggregate-func>("#"<mrollup-aggregate-func>)?)*))? (app=<string>)?

## Description
rollup or summarize data from source to target index Rollup metric data in to another index for storage/search performance improvements.


## Syntax
mrollup (source=<string>) (target=<string>) (file=<string>)? (span=<string:timespan>) (aggregate=(<mrollup-aggregate-func>("#"<mrollup-aggregate-func>)?)*)? (dimension-list=(<string>,<string>))? (dimension-list-type=(excluded|included))? (metric-list=(<string>,<string>))? (metric-list-type=(excluded|included))? (metric-overrides=(<string>;(<mrollup-aggregate-func>("#"<mrollup-aggregate-func>)?)*))? (app=<string>)?

## Description
rollup or summarize data from source to target index Rollup metric data in to another index for storage/search performance improvements.
 