import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { API_BASE_URL } from './api';
import {
  CatalogIngredientRead,
  CustomIngredientRead,
  CustomIngredientUpdate,
  FoodItemInput,
  FoodItemList,
  FoodDataSource,
  FoodItemRead,
  ProductRead,
  ProductSummaryRead,
  RecentFood,
} from './api-types';

@Injectable({ providedIn: 'root' })
export class FoodService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = inject(API_BASE_URL);

  // The catalog is reference data that only changes with a deploy, so one copy
  // per page load is enough, and every food editor on the screen shares it.
  private catalogRequest: Promise<CatalogIngredientRead[]> | null = null;

  private get foods(): string {
    return `${this.baseUrl}/me/foods`;
  }

  catalog(): Promise<CatalogIngredientRead[]> {
    this.catalogRequest ??= firstValueFrom(
      this.http.get<CatalogIngredientRead[]>(`${this.baseUrl}/foods/ingredients`),
    ).catch((failure: unknown) => {
      // A failed request must not be cached, or one network blip would leave
      // search empty until the page is reloaded.
      this.catalogRequest = null;
      throw failure;
    });
    return this.catalogRequest;
  }

  /**
   * Product search and lookup go through our API, never straight to the food
   * databases, so neither learns which patient is asking.
   */
  async searchProducts(query: string, limit = 12): Promise<ProductSummaryRead[]> {
    return firstValueFrom(
      this.http.get<ProductSummaryRead[]>(`${this.baseUrl}/foods/products/search`, {
        params: { q: query, limit },
      }),
    );
  }

  async productByBarcode(barcode: string): Promise<ProductRead> {
    return firstValueFrom(
      this.http.get<ProductRead>(
        `${this.baseUrl}/foods/products/barcode/${encodeURIComponent(barcode)}`,
      ),
    );
  }

  async product(source: FoodDataSource, sourceId: string): Promise<ProductRead> {
    return firstValueFrom(
      this.http.get<ProductRead>(
        `${this.baseUrl}/foods/products/${source}/${encodeURIComponent(sourceId)}`,
      ),
    );
  }

  async customIngredients(): Promise<CustomIngredientRead[]> {
    return firstValueFrom(this.http.get<CustomIngredientRead[]>(`${this.foods}/ingredients`));
  }

  async updateCustomIngredient(
    id: string,
    update: CustomIngredientUpdate,
  ): Promise<CustomIngredientRead> {
    return firstValueFrom(
      this.http.patch<CustomIngredientRead>(`${this.foods}/ingredients/${id}`, update),
    );
  }

  async forDay(day: string): Promise<FoodItemRead[]> {
    const list = await firstValueFrom(
      this.http.get<FoodItemList>(this.foods, { params: { from: day, to: day } }),
    );
    return list.items;
  }

  async recent(limit = 6): Promise<RecentFood[]> {
    return firstValueFrom(
      this.http.get<RecentFood[]>(`${this.foods}/recent`, { params: { limit } }),
    );
  }

  async log(item: FoodItemInput): Promise<FoodItemRead> {
    return firstValueFrom(this.http.post<FoodItemRead>(this.foods, item));
  }

  async update(id: string, item: FoodItemInput): Promise<FoodItemRead> {
    return firstValueFrom(this.http.put<FoodItemRead>(`${this.foods}/${id}`, item));
  }

  async remove(id: string): Promise<void> {
    await firstValueFrom(this.http.delete(`${this.foods}/${id}`));
  }
}
