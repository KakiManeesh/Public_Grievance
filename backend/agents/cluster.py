"""
cluster.py — Agent 3 in the civic complaint pipeline.

Groups spatially close complaints of the same category together using DBSCAN
to detect hotspots. Runs one DBSCAN pass per category to prevent cross-category
merging. Cluster IDs are namespaced with the category (e.g. "Roads_0").
"""

import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN

# DBSCAN parameters — 2.0 km expressed in radians on Earth's surface
_EPS: float = 2.0 / 6371
_MIN_SAMPLES: int = 2
_METRIC: str = "haversine"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def cluster(complaints: list[dict]) -> list[dict]:
    """Group same-category complaints within 2.0 km using per-category DBSCAN; adds cluster_id to each dict."""

    if not complaints:
        return complaints

    df = pd.DataFrame(complaints)

    # Initialise all cluster_id values to -1 (isolated / no cluster).
    # Use object dtype so string labels ("Roads_0") and int -1 coexist without
    # triggering a pandas FutureWarning / dtype incompatibility error.
    df["cluster_id"] = pd.array([-1] * len(df), dtype=object)

    try:
        for category in df["category"].unique():
            mask = df["category"] == category
            cat_df = df.loc[mask]

            # Need at least 2 rows for DBSCAN to form any cluster
            if len(cat_df) < 2:
                continue

            try:
                coords = np.radians(cat_df[["lat", "lng"]].values.astype(float))
                db = DBSCAN(eps=_EPS, min_samples=_MIN_SAMPLES, metric=_METRIC)
                labels = db.fit_predict(coords)

                namespaced = [
                    f"{category}_{label}" if label != -1 else -1
                    for label in labels
                ]

                df.loc[mask, "cluster_id"] = namespaced

                # Assign -1 to nearest cluster in same category
                cat_df_updated = df.loc[mask]
                isolated_mask = cat_df_updated["cluster_id"] == -1
                clustered_mask = cat_df_updated["cluster_id"] != -1
                
                if isolated_mask.any() and clustered_mask.any():
                    from sklearn.metrics.pairwise import haversine_distances
                    isolated_coords = np.radians(cat_df_updated.loc[isolated_mask, ["lat", "lng"]].values.astype(float))
                    clustered_coords = np.radians(cat_df_updated.loc[clustered_mask, ["lat", "lng"]].values.astype(float))
                    clustered_ids = cat_df_updated.loc[clustered_mask, "cluster_id"].values
                    
                    dist_matrix = haversine_distances(isolated_coords, clustered_coords)
                    nearest_indices = dist_matrix.argmin(axis=1)
                    
                    nearest_ids = clustered_ids[nearest_indices]
                    df.loc[mask & (df["cluster_id"] == -1), "cluster_id"] = nearest_ids

            except Exception:
                # On any per-category failure leave those rows at -1
                continue

    except Exception:
        # If iteration itself fails, return all rows with cluster_id = -1
        df["cluster_id"] = -1

    # Guard: never silently drop a row
    output = df.to_dict(orient="records")
    if len(output) != len(complaints):
        raise ValueError(
            f"Silent row drop detected in cluster(): "
            f"{len(complaints)} in → {len(output)} out."
        )

    return output


def get_cluster_summaries(complaints: list[dict]) -> list[dict]:
    """Return one summary dict per cluster (excluding isolated -1 complaints)."""

    if not complaints:
        return []

    try:
        df = pd.DataFrame(complaints)

        # Exclude isolated complaints
        clustered = df[df["cluster_id"] != -1].copy()

        if clustered.empty:
            return []

        summaries: list[dict] = []

        for cluster_id, group in clustered.groupby("cluster_id"):
            try:
                # Dominant priority = most frequent value; ties broken by first occurrence
                dominant_priority: str = (
                    group["priority"].value_counts().idxmax()
                    if "priority" in group.columns
                    else "Medium"
                )

                centroid_lat: float = round(float(group["lat"].mean()), 6)
                centroid_lng: float = round(float(group["lng"].mean()), 6)

                # category is uniform within a cluster (DBSCAN per-category guarantees this)
                category: str = str(group["category"].iloc[0])

                complaint_ids: list[int] = group["id"].tolist()

                summaries.append({
                    "cluster_id":        str(cluster_id),
                    "category":          category,
                    "complaint_ids":     complaint_ids,
                    "centroid":          {"lat": centroid_lat, "lng": centroid_lng},
                    "count":             len(group),
                    "dominant_priority": dominant_priority,
                })

            except Exception:
                # Skip a malformed cluster rather than crashing the whole summary
                continue

        return summaries

    except Exception:
        return []
