# honua-arcpy compatibility matrix

Generated from the in-code ``COMPAT`` manifest by ``scripts/render_compat_matrix.py`` (re-run after manifest edits).

Statuses: **Supported** runs against Honua, **Partial** runs with documented deviations, **Stub** raises ``HonuaArcpyUnsupportedError`` with a replacement hint and tracking ticket.

## arcpy.analysis.*

| Function | Status | Backend | Replacement / notes |
| --- | --- | --- | --- |
| <a id="analysisbuffer"></a>`arcpy.analysis.Buffer` | Supported | `process` | Vector buffer; dispatches to honua-server geometry.buffer. |
| <a id="analysisclip"></a>`arcpy.analysis.Clip` | Supported | `process` | Vector clip against another feature class. |
| <a id="analysiserase"></a>`arcpy.analysis.Erase` | Supported | `process` | Vector erase (arcpy's name for geometric difference). |
| <a id="analysisidentity"></a>`arcpy.analysis.Identity` | Stub | `not-implemented` | Computes geometric identity between two layers.<br>**hint:** Compose Intersect + retain unmatched input rows client-side.<br>**tracking:** `honua-server#identity` |
| <a id="analysisintersect"></a>`arcpy.analysis.Intersect` | Supported | `process` | Pairwise vector intersect; respects join_attributes. |
| <a id="analysismultipleringbuffer"></a>`arcpy.analysis.MultipleRingBuffer` | Stub | `not-implemented` | Multi-ring buffer wraps geometry.buffer across distance bands.<br>**hint:** Loop honua_arcpy.analysis.Buffer over each distance band and merge.<br>**tracking:** `honua-server#multiple-ring-buffer` |
| <a id="analysisnear"></a>`arcpy.analysis.Near` | Stub | `not-implemented` | Computes distance to nearest feature; requires honua-server analytics process.<br>**hint:** Use honua_sdk.Source.query(...) with bbox + spatial filter and minimize distance client-side.<br>**tracking:** `honua-server#near` |
| <a id="analysisnearestneighbor"></a>`arcpy.analysis.NearestNeighbor` | Stub | `not-implemented` | Average nearest neighbor; requires honua-server analytics process.<br>**hint:** Use honua_sdk.Source.query(...) with sort_by_distance and compute the ratio client-side.<br>**tracking:** `honua-server#nearest-neighbor` |
| <a id="analysispointdistance"></a>`arcpy.analysis.PointDistance` | Stub | `not-implemented` | Point-to-point distance matrix; requires honua-server analytics process.<br>**hint:** Use honua_sdk.Source.query(...) and compute pairwise distance client-side.<br>**tracking:** `honua-server#point-distance` |
| <a id="analysisspatialjoin"></a>`arcpy.analysis.SpatialJoin` | Supported | `process` | Spatial join with optional match-option and search radius. |
| <a id="analysissummarizewithin"></a>`arcpy.analysis.SummarizeWithin` | Stub | `not-implemented` | Aggregates features inside polygon bins.<br>**hint:** Use analytics.spatial-join + groupby aggregation on the OGC API Features client.<br>**tracking:** `honua-server#summarize-within` |
| <a id="analysissymmetricaldifference"></a>`arcpy.analysis.SymmetricalDifference` | Stub | `not-implemented` | Returns features that fall in exactly one input.<br>**hint:** Compose Union minus Intersect; both processes are supported.<br>**tracking:** `honua-server#symmetrical-difference` |
| <a id="analysistabulateintersection"></a>`arcpy.analysis.TabulateIntersection` | Stub | `not-implemented` | Cross-tabulates area / length of intersection.<br>**hint:** Use analytics.spatial-join + summarize-within client-side post-processing.<br>**tracking:** `honua-server#tabulate-intersection` |
| <a id="analysisunion"></a>`arcpy.analysis.Union` | Supported | `process` | Vector union; gaps allowance forwarded as a process parameter. |
| <a id="analysisupdate"></a>`arcpy.analysis.Update` | Stub | `not-implemented` | Replaces input geometries with updater layer features.<br>**hint:** Use admin apply_manifest with a replace operation.<br>**tracking:** `honua-server#update-analysis` |

## arcpy.management.*

| Function | Status | Backend | Replacement / notes |
| --- | --- | --- | --- |
| <a id="managementaddfield"></a>`arcpy.management.AddField` | Stub | `not-implemented` | Schema-mutating field add; HonuaAdminClient has no add_field/apply_manifest path that mutates layer schemas today.<br>**hint:** File a honua-server ticket for layer-schema mutation; meanwhile run schema changes through your manifest publishing flow.<br>**tracking:** `honua-server#layer-schema-mutate` |
| <a id="managementappend"></a>`arcpy.management.Append` | Stub | `not-implemented` | Append rows from inputs into a target table.<br>**hint:** Use honua_sdk.Source.apply_edits with adds payload after schema-translation.<br>**tracking:** `honua-server#append` |
| <a id="managementcalculatefield"></a>`arcpy.management.CalculateField` | Supported | `process` | Python expression sent to server-side calculator. |
| <a id="managementcopy"></a>`arcpy.management.Copy` | Supported | `process` | Copies features into a new resource via copy-features process. |
| <a id="managementcreatefeatureclass"></a>`arcpy.management.CreateFeatureclass` | Stub | `not-implemented` | Creates a new feature class; schema translation is the hard part.<br>**hint:** Use honua_admin.HonuaAdminClient.apply_manifest with a create-resource entry.<br>**tracking:** `honua-server#create-feature-class` |
| <a id="managementcreatetable"></a>`arcpy.management.CreateTable` | Stub | `not-implemented` | Creates a new table; schema translation is the hard part.<br>**hint:** Use honua_admin.HonuaAdminClient.apply_manifest with a create-resource entry.<br>**tracking:** `honua-server#create-table` |
| <a id="managementdelete"></a>`arcpy.management.Delete` | Supported | `process` | Deletes a feature class or table. |
| <a id="managementdeletefield"></a>`arcpy.management.DeleteField` | Stub | `not-implemented` | Schema-mutating field delete; HonuaAdminClient has no delete_field/apply_manifest path that mutates layer schemas today.<br>**hint:** File a honua-server ticket for layer-schema mutation; meanwhile run schema changes through your manifest publishing flow.<br>**tracking:** `honua-server#layer-schema-mutate` |
| <a id="managementdescribe"></a>`arcpy.management.Describe` | Stub | `not-implemented` | Inspects a dataset's schema; HonuaAdminClient does not expose a per-layer schema reader today.<br>**hint:** Use honua_admin.HonuaAdminClient.discover_tables for the parent connection or honua_sdk.HonuaClient.feature_server(...).layer_metadata(layer_id).<br>**tracking:** `honua-server#layer-schema-read` |
| <a id="managementdissolve"></a>`arcpy.management.Dissolve` | Supported | `process` | Geometry dissolve on optional field list. |
| <a id="managementgetcount"></a>`arcpy.management.GetCount` | Partial | `source` | Returns a row count via Source.query; currently materializes the full result set because Source has no count-only helper yet. |
| <a id="managementlistfields"></a>`arcpy.management.ListFields` | Stub | `not-implemented` | Lists layer fields; HonuaAdminClient exposes discover_tables (per connection) but no per-layer schema reader today.<br>**hint:** Use honua_admin.HonuaAdminClient.discover_tables for the parent connection and project the field list locally.<br>**tracking:** `honua-server#layer-schema-read` |
| <a id="managementmakefeaturelayer"></a>`arcpy.management.MakeFeatureLayer` | Supported | `session` | Creates an in-process layer alias; deviation: alias is bound to a Honua source descriptor. |
| <a id="managementmaketableview"></a>`arcpy.management.MakeTableView` | Supported | `session` | Creates an in-process table-view alias; mirrors MakeFeatureLayer. |
| <a id="managementmerge"></a>`arcpy.management.Merge` | Stub | `not-implemented` | Merges multiple feature classes into one.<br>**hint:** Iterate honua_sdk.Source.iter_features and write via apply_edits in chunks.<br>**tracking:** `honua-server#merge` |
| <a id="managementproject"></a>`arcpy.management.Project` | Supported | `process` | Reprojects a feature class via conversion.feature-project. |
| <a id="managementrename"></a>`arcpy.management.Rename` | Stub | `not-implemented` | Resource rename; HonuaAdminClient exposes apply_manifest but no rename_resource translation today.<br>**hint:** Republish the resource under the new name via honua_admin.HonuaAdminClient.apply_manifest and delete the old entry.<br>**tracking:** `honua-server#rename-resource` |
| <a id="managementselectlayerbyattribute"></a>`arcpy.management.SelectLayerByAttribute` | Supported | `source` | Where-clause selection; updates the in-process layer state. |
| <a id="managementselectlayerbylocation"></a>`arcpy.management.SelectLayerByLocation` | Stub | `not-implemented` | Spatial selection composed of buffer + intersect when no native process exists.<br>**hint:** Use honua_arcpy.analysis.Buffer + analysis.Intersect, then SelectLayerByAttribute.<br>**tracking:** `honua-server#spatial-filter` |
| <a id="managementsort"></a>`arcpy.management.Sort` | Stub | `not-implemented` | Sorts feature class rows by one or more fields.<br>**hint:** Use honua_sdk.Source.query(order_by=...) and write with apply_edits.<br>**tracking:** `honua-server#sort` |

## arcpy.da.*

| Function | Status | Backend | Replacement / notes |
| --- | --- | --- | --- |
| <a id="daeditor"></a>`arcpy.da.Editor` | Stub | `not-implemented` | Workspace-level edit session context manager.<br>**hint:** Wrap honua_sdk.Source.apply_edits calls in a try/except; per-workspace transactions are not yet exposed.<br>**tracking:** `honua-server#workspace-editor` |
| <a id="daextendtable"></a>`arcpy.da.ExtendTable` | Stub | `not-implemented` | Joins a NumPy array onto an existing table.<br>**hint:** Use admin apply_manifest with a field-add + apply_edits update sequence.<br>**tracking:** `honua-server#extend-table` |
| <a id="dafeatureclasstonumpyarray"></a>`arcpy.da.FeatureClassToNumPyArray` | Stub | `not-implemented` | Materializes feature class rows as a NumPy structured array.<br>**hint:** Use honua_sdk.Source.query(...).features and convert with numpy.array client-side.<br>**tracking:** `honua-server#numpy-bridge` |
| <a id="dainsertcursor"></a>`arcpy.da.InsertCursor` | Supported | `source` | Buffered inserts; flush on __exit__. Deviates from arcpy's per-row commit. |
| <a id="danumpyarraytofeatureclass"></a>`arcpy.da.NumPyArrayToFeatureClass` | Stub | `not-implemented` | Writes a NumPy structured array into a feature class.<br>**hint:** Use honua_sdk.Source.apply_edits with feature rows derived from the structured array.<br>**tracking:** `honua-server#numpy-bridge` |
| <a id="danumpyarraytotable"></a>`arcpy.da.NumPyArrayToTable` | Stub | `not-implemented` | Writes a NumPy structured array into a table.<br>**hint:** Use honua_sdk.Source.apply_edits with rows derived from the structured array.<br>**tracking:** `honua-server#numpy-bridge` |
| <a id="dasearchcursor"></a>`arcpy.da.SearchCursor` | Supported | `source` | Read-only iteration over Source.iter_features; context-manager safe. |
| <a id="databletonumpyarray"></a>`arcpy.da.TableToNumPyArray` | Stub | `not-implemented` | Materializes table rows as a NumPy structured array.<br>**hint:** Use honua_sdk.Source.query(...).features and convert with numpy.array client-side.<br>**tracking:** `honua-server#numpy-bridge` |
| <a id="daupdatecursor"></a>`arcpy.da.UpdateCursor` | Supported | `source` | Buffered updates; flush on __exit__ or explicit cursor.flush(). Deviates from arcpy's per-row commit. |
| <a id="dawalk"></a>`arcpy.da.Walk` | Stub | `not-implemented` | Walks a workspace directory tree for datasets.<br>**hint:** Use honua_admin.HonuaAdminClient.list_services / list_metadata_resources.<br>**tracking:** `honua-server#workspace-walk` |

## Coverage

* Total functions: 45
* Supported / partial: 18
* Stubbed (raise ``HonuaArcpyUnsupportedError``): 27

Stubs intentionally raise rather than silently fail so customer scripts surface gaps before the migration tool ingests the audit JSONL.
