import type { ACNetGeneratedModelConfig } from '../pipeline';

export type ACNetGeneratedModelLoader = () => Promise<ACNetGeneratedModelConfig>;

export const acnetGeneratedModelLoaders: Record<string, ACNetGeneratedModelLoader> = {
  "ACNET_F8B18_HDN": async () => (await import(/* webpackChunkName: "acnet-effect-acnet-f8b18-hdn" */ './acnet_f8b18_hdn')).default,
  "ACNET_F8B18": async () => (await import(/* webpackChunkName: "acnet-effect-acnet-f8b18" */ './acnet_f8b18')).default,
  "ACNET_F8B8": async () => (await import(/* webpackChunkName: "acnet-effect-acnet-f8b8" */ './acnet_f8b8')).default,
};
