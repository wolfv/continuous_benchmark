# Continuous Benchmarking

This repository contains continuous benchmarking tools for benchmarking libraries 
such as google benchmark. The script expects a CSV file of google benchmarks format.

The upload results script will create a gist per branch, upload the newly created data and
create analyses against previously run benchmarks. 
It will send out emails to alert of changes in the performance. Additionally it can push data 
to a Grafana/Graphite server to create nice plots of the performance over time.
