export interface ACNetGeneratedModelMeta {
  key: string;
  id: string;
  name: string;
  family: string;
  directory: string;
  stageCount: number;
}

export const acnetGeneratedModelMetas: ACNetGeneratedModelMeta[] = [
  {
    "key": "ACNET_F8B18_HDN",
    "id": "acnet/Upscale/F8B18_HDN",
    "name": "ACNet F8B18 HDN",
    "family": "acnet",
    "directory": "acnet_f8b18_hdn",
    "stageCount": 40
  },
  {
    "key": "ACNET_F8B18",
    "id": "acnet/Upscale/F8B18",
    "name": "ACNet F8B18",
    "family": "acnet",
    "directory": "acnet_f8b18",
    "stageCount": 40
  },
  {
    "key": "ACNET_F8B8",
    "id": "acnet/Upscale/F8B8",
    "name": "ACNet F8B8",
    "family": "acnet",
    "directory": "acnet_f8b8",
    "stageCount": 20
  },
];
