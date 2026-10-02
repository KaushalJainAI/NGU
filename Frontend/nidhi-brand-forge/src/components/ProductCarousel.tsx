import {
  Carousel,
  CarouselContent,
  CarouselItem,
  CarouselPrevious,
  CarouselNext,
} from "@/components/ui/carousel";
import ProductCard from "@/components/ProductCard";

export interface CarouselProductItem {
  id: number;
  name: string;
  image: string;
  price: number;
  originalPrice?: number;
  weight?: string;
  badge?: string;
  itemType?: "product" | "combo";
}

interface ProductCarouselProps {
  items: CarouselProductItem[];
}

/**
 * Horizontally-scrolling row of ProductCards.
 *
 * Wraps the shared Embla carousel (components/ui/carousel) so several products
 * are visible with overflow: arrow buttons on desktop, native swipe on touch.
 * Replaces the old fixed 4-column grids on the homepage.
 */
const ProductCarousel = ({ items }: ProductCarouselProps) => {
  if (!items?.length) return null;

  return (
    <Carousel
      opts={{ align: "start", dragFree: true }}
      className="w-full"
    >
      <CarouselContent className="-ml-3 sm:-ml-4">
        {items.map((item) => (
          <CarouselItem
            key={`${item.itemType || "product"}-${item.id}`}
            className="pl-3 sm:pl-4 basis-[72%] min-[420px]:basis-1/2 sm:basis-1/3 lg:basis-1/4 xl:basis-1/5"
          >
            <ProductCard {...item} />
          </CarouselItem>
        ))}
      </CarouselContent>
      {/* Arrows are hidden on small screens where swipe is natural. */}
      <CarouselPrevious className="hidden sm:flex -left-3 lg:-left-5" />
      <CarouselNext className="hidden sm:flex -right-3 lg:-right-5" />
    </Carousel>
  );
};

export default ProductCarousel;
