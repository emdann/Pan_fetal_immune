### Save pseudobulk data for differential expression analysis ###
import os,sys
import scanpy as sc
import pandas as pd
import numpy as np
import scipy.io
import gzip
import shutil

import argparse
parser = argparse.ArgumentParser()
parser.add_argument("timestamp", help="data timestamp")
parser.add_argument("--indir", 
                    default="/nfs/team205/ed6/data/Fetal_immune/",
                    help="folder containing anndata obj")
parser.add_argument("--split_name", 
                    default="",
                    help="ID for data split (e.g. NKT, Progenitors, Stroma...) (default: no split, full atlas)")
args = parser.parse_args()

def zip_file(indir, filename):
    with open(os.path.join(indir,filename),'rb') as f_in:
        with gzip.open(os.path.join(indir,filename) + '.gz','wb') as f_gz:
            shutil.copyfileobj(f_in, f_gz)
    os.remove(os.path.join(indir,filename)) 

def save_4_de(adata, adata_id, covs=["Sample", "donor", "organ", "anno_lvl_2", "age", "method"]):
    input_data_dir = "/nfs/team205/ed6/data/Fetal_immune/LMM_data/DE_input_{id}/".format(id=adata_id)
    if not os.path.exists(input_data_dir):
        os.mkdir(input_data_dir)
    # Save log-counts matrix
    scipy.io.mmwrite(input_data_dir + "matrix.mtx", adata.X)
    zip_file(input_data_dir, 'matrix.mtx')
    # Save gene names
    adata.var.to_csv(input_data_dir + 'gene.csv')
    zip_file(input_data_dir, 'gene.csv')
    # Save metadata
    lmm_metadata = adata.obs[covs]
    lmm_metadata.to_csv(input_data_dir + 'metadata.csv')
    zip_file(input_data_dir, 'metadata.csv')

    
def anndata2pseudobulk(adata, group_by, agg="s", min_ncells = 10):
    '''
    Params:
    ------
    adata: the anndata object
    group_by: list of obs columns to use for aggregation
    agg: "s" for sum (if adata.X are counts), "m" for mean (if adata.X are log-counts)
    min_ncells: minimum number of cells to keep pseudobulk sample (default=10)
    '''
    from scipy.sparse import csr_matrix
    import anndata
    if agg=="s" and "log1p" in adata.uns_keys():
        print("adata.X is in log-transformed, pseudobulking should be done on counts")
        return()
    ## Make obs for pseudobulk
    pseudobulk_obs = adata.obs[group_by].drop_duplicates()
    pseudobulk_obs = pseudobulk_obs[group_by].astype("str")
    pseudobulk_obs.index = pseudobulk_obs[group_by].agg("-".join, axis=1)
    ## Add column to obs assigning cells to pseudobulk samples
    adata.obs[group_by] = adata.obs[group_by].astype("str")
    adata.obs["pseudobulk_sample"] = adata.obs[group_by].agg("-".join, axis=1)
    ## Sum counts from same sample
    sample_dummies = pd.get_dummies(adata.obs["pseudobulk_sample"])[pseudobulk_obs.index].values
    sample_dummies = scipy.sparse.csr_matrix(sample_dummies)
    pseudobulk_X = adata.X.T.dot(sample_dummies)
    ## Check that pseudobulk profiles are the sum of all profiles in a sample
    a = np.array(adata[sample_dummies[:,0]!=0].X.sum(0)).flatten()
    b = pseudobulk_X[:,0].toarray().flatten()
    if not np.all(a == b):
        print("Error! Aggregation doesn't coincide with sum across the same sample")
        return()
    if agg=="m":
        pseudobulk_X = csr_matrix(pseudobulk_X / sample_dummies.toarray().sum(0))
    ## Make new anndata object
    pseudobulk_adata = anndata.AnnData(pseudobulk_X.T, obs=pseudobulk_obs, var=adata.var)
    ## Add number of cells to obs 
    n_cells = adata.obs.groupby('pseudobulk_sample').count().iloc[:,0]
    n_cells.name = "n_cells"
    pseudobulk_adata.obs = pd.concat([pseudobulk_adata.obs, n_cells], axis=1)
    ## Filter obs by number of cells threshold
    pseudobulk_adata = pseudobulk_adata[pseudobulk_adata.obs['n_cells'] >= min_ncells]
    return(pseudobulk_adata)


### Load full data ###
timestamp = args.timestamp
data_dir = args.indir
spl = args.split_name
if len(spl)==0:
    h5ad_file = data_dir + 'PAN.A01.v01.entire_data_raw_count.{t}.h5ad'.format(t=timestamp)
else:
    h5ad_file = data_dir + 'PAN.A01.v01.entire_data_raw_count.{t}.{s}.h5ad'.format(t=timestamp, s=spl)

print("Loading data...")
adata = sc.read_h5ad(h5ad_file)

## Filter maternal contaminants
mat_barcodes = pd.read_csv("~/Pan_fetal_immune/metadata/souporcell_results/maternal_barcodes.csv", index_col=0)
mat_barcodes["x"] = pd.Series([x.split("-1")[0] for x in mat_barcodes['x']])
adata = adata[~adata.obs_names.isin(mat_barcodes["x"])]

# Add annotation obs
# anno_dir = "/nfs/team205/ed6/bin/Pan_fetal_immune/metadata/manual_annotation/"
anno_obs = pd.read_csv(data_dir + "PAN.A01.v01.entire_data_normalised_log.20210429.full_obs.annotated.clean.csv", index_col=0)
adata = adata[adata.obs_names.isin(anno_obs.index)].copy()
covs = ["Sample", "donor", "organ", "anno_lvl_2_final_clean", "age", "method"]
for c in covs:
    adata.obs[c] = anno_obs.loc[adata.obs_names][c]

### Pseudobulking ###
pseudobulk=True
if pseudobulk:
    adata = anndata2pseudobulk(adata, ["Sample", "donor", "organ", "anno_lvl_2_final_clean", "age", "method"], agg="s")
    adata_id = spl + "_PBULK"
else:
    adata_id = spl

### Save data
save_4_de(adata, adata_id, covs=["Sample", "donor", "organ", "anno_lvl_2_final_clean", "age", "method", "n_cells"])

