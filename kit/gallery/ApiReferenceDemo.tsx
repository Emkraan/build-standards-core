/* The API reference specimen body. It is its own module so the gallery loads the Scalar app only
   when a reader opens the specimen: the gate and the a11y run never pull it. Its sheet is imported
   with the other sheets in main.tsx. */

import { ApiReference } from '../src/api-reference';

/** A small neutral OpenAPI document: two read endpoints and one write, behind a bearer token. */
const SAMPLE_SPEC = {
  openapi: '3.1.0',
  info: {
    title: 'Example API',
    version: '1.0.0',
    description: 'A sample document for the kit gallery. Every value here is made up.',
  },
  servers: [{ url: 'https://api.example.test/v1' }],
  security: [{ bearer: [] }],
  components: {
    securitySchemes: { bearer: { type: 'http', scheme: 'bearer' } },
    schemas: {
      Device: {
        type: 'object',
        required: ['id', 'name', 'status'],
        properties: {
          id: { type: 'string', example: 'dev-0042' },
          name: { type: 'string', example: 'Kiosk 12' },
          status: { type: 'string', enum: ['healthy', 'degraded', 'offline'] },
          lastSeen: { type: 'string', format: 'date-time' },
        },
      },
    },
  },
  paths: {
    '/devices': {
      get: {
        summary: 'List devices',
        tags: ['Devices'],
        parameters: [{ name: 'status', in: 'query', schema: { type: 'string' } }],
        responses: {
          '200': {
            description: 'The devices',
            content: { 'application/json': { schema: { type: 'array', items: { $ref: '#/components/schemas/Device' } } } },
          },
        },
      },
      post: {
        summary: 'Enrol a device',
        tags: ['Devices'],
        requestBody: { content: { 'application/json': { schema: { $ref: '#/components/schemas/Device' } } } },
        responses: { '201': { description: 'Enrolled' } },
      },
    },
    '/devices/{id}': {
      get: {
        summary: 'Get a device',
        tags: ['Devices'],
        parameters: [{ name: 'id', in: 'path', required: true, schema: { type: 'string' } }],
        responses: {
          '200': { description: 'The device', content: { 'application/json': { schema: { $ref: '#/components/schemas/Device' } } } },
          '404': { description: 'No such device' },
        },
      },
    },
  },
};

export default function ApiReferenceDemo() {
  return <ApiReference content={SAMPLE_SPEC} title="Example API" headingLevel={3} />;
}
