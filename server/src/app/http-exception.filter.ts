import {
  ArgumentsHost,
  Catch,
  HttpException,
  type ExceptionFilter,
} from '@nestjs/common';

import { VisionProviderError } from '../adapters/vision.gemini';
import { PackUnavailableError } from '../locales/loader';

interface HttpResponse {
  status(code: number): HttpResponse;
  json(body: unknown): void;
}

interface HttpRequest {
  headers: Record<string, string | string[] | undefined>;
}

function responseText(payload: unknown): string {
  if (typeof payload === 'string') return payload;
  try {
    return JSON.stringify(payload) ?? '';
  } catch {
    return '';
  }
}

/** Keep parser and Multer failures on the Python API's wire contract. */
@Catch()
export class HttpExceptionFilter implements ExceptionFilter {
  catch(exception: unknown, host: ArgumentsHost): void {
    const context = host.switchToHttp();
    const response = context.getResponse<HttpResponse>();
    const request = context.getRequest<HttpRequest>();

    if (exception instanceof VisionProviderError) {
      response.status(503).json({
        detail: exception.detail,
        category: exception.category,
        retry_attempted: exception.attempts > 1,
        attempts: exception.attempts,
      });
      return;
    }

    if (exception instanceof PackUnavailableError) {
      // The pack exists and its licence is declared; this deployment just does
      // not carry the restricted catalogue. That is a configuration state, not
      // a client error, so it must not look like an unknown locale.
      response.status(503).json({
        detail: 'locale catalogue is not installed in this deployment',
        locale: exception.locale,
        reason: exception.reason,
      });
      return;
    }

    if (exception instanceof HttpException) {
      const status = exception.getStatus();
      const payload = exception.getResponse();
      const text = responseText(payload);

      // FileInterceptor translates Multer's LIMIT_FILE_SIZE into a 400. The
      // Python boundary treats an image over the limit as a payload error.
      if ((status === 400 || status === 413) && /file too large|limit_file_size/i.test(text)) {
        response.status(413).json({ detail: 'image exceeds 10 MiB limit' });
        return;
      }

      // Express's JSON parser reports malformed JSON as a 400 before the
      // controller runs; FastAPI exposes that boundary as a 422.
      const contentType = (request.headers?.['content-type'] ?? request.headers?.['Content-Type']) as string | undefined;
      const combinedError = `${text} ${exception.message || ''}`;
      if (
        status === 400
        && (
          (typeof contentType === 'string' && contentType.toLowerCase().includes('application/json'))
          || /unexpected|json|syntaxerror/i.test(combinedError)
        )
        && /unexpected|json parse|invalid json|syntaxerror/i.test(combinedError)
      ) {
        response.status(422).json({ detail: 'invalid JSON request' });
        return;
      }


      if (typeof payload === 'object' && payload !== null) {
        response.status(status).json(payload);
      } else {
        response.status(status).json({ detail: String(payload) });
      }
      return;
    }

    const code = (exception as { code?: unknown } | null)?.code;
    if (code === 'LIMIT_FILE_SIZE') {
      response.status(413).json({ detail: 'image exceeds 10 MiB limit' });
      return;
    }

    response.status(500).json({ detail: 'Internal Server Error' });
  }
}
