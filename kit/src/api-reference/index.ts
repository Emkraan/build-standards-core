/* The API reference entry (`kit-core/api-reference`). Scalar is an optional peer dependency, so the
   reference lives behind its own entry: an app that never renders one never installs or bundles
   Scalar, and the kit root keeps zero runtime dependencies. Import api-reference.css once,
   after kit.css. */

export { ApiReference, demoteHeadings, nestMainLandmarks, scalarConfiguration } from './ApiReference';
export type { ApiReferenceProps, ApiReferenceServer } from './ApiReference';
